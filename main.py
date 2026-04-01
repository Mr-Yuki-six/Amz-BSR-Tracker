import os
import re
import time
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import ChromiumOptions, ChromiumPage
import json

# 加载 .env 文件中的敏感配置
load_dotenv()


# ================= 1. 数据库连接配置 =================
def get_db_connection():
    """获取 PostgreSQL 数据库连接"""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        return conn
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return None


# ================= 2. 浏览器基础配置 =================
def setup_browser():
    co = ChromiumOptions()
    co.headless(True)
    co.mute(True)
    co.no_imgs(True)
    co.set_user_data_path(r'./bot_data')
    co.set_argument('--lang=en-US')
    co.set_user_agent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return ChromiumPage(co)


# ================= 3. 数据清洗与抓取逻辑 =================
def fetch_and_clean_bsr(asin, page):
    url = f"https://www.amazon.com/dp/{asin}?language=en_US"
    tab = page.new_tab(url)

    # 【改动 1】扩充结果字典，装载新字段
    result = {
        "asin": asin,
        "title": None, "brand": None,
        "material": None, "back_material": None, "item_shape": None, "size": None,  # 新增静态属性
        "main_category": None, "main_rank": None,
        "sub_category": None, "sub_rank": None,
        "rating": None, "reviews": None,  # 新增动态属性
        "status": "failed"
    }

    try:
        tab.wait.load_start()
        bot_btn = tab.ele('text:Continue shopping', timeout=0.5)
        if bot_btn:
            bot_btn.click()
            tab.wait(2)

        # 提取标题
        try:
            title_ele = tab.ele('#productTitle', timeout=1)
            if title_ele:
                result["title"] = title_ele.text.strip()
            else:
                meta_content = tab.ele('tag:meta@name=title').attr('content')
                if meta_content:
                    result["title"] = meta_content.replace("Amazon.com: ", "").split(" : ")[0].strip()
        except Exception:
            pass

        tab.scroll.to_half()
        tab.wait(0.5)
        tab.scroll.to_bottom()
        tab.wait(0.5)

        # 【新增：批量提取表格中的静态属性 (Brand, Material, Shape, Size)】
        # 我们用一个字典循环来抓，代码极其优雅干净
        attributes_to_find = {
            "Brand": "brand",
            "Brand Name": "brand",
            "Material Type": "material",
            "Back Material Type": "back_material",
            "Item Shape": "item_shape",
            "Size": "size"
        }

        for label, key in attributes_to_find.items():
            try:
                # 【核心修改】使用 XPath 精准狙击！
                # 意思是：只找 <th> 标签，且无视空格后，文本完全等于 label 的元素
                xpath_str = f'xpath://th[normalize-space(text())="{label}"]'
                th_ele = tab.ele(xpath_str, timeout=0.2)

                if th_ele and not result[key]:
                    # 找到表头后，去同级别的 <td> 里拿数据
                    result[key] = th_ele.parent('tag:tr').ele('tag:td').text.strip()
            except Exception:
                continue  # 找不到就安安静静跳过，不影响下一个

        # 【新增：提取动态评价指标 (Rating, Reviews)】
        try:
            # 寻找带有 data-rating 属性的节点
            rating_ele = tab.ele('@data-rating', timeout=0.5)
            if rating_ele:
                rating_str = rating_ele.attr('data-rating')  # "4.4 out of 5 stars"
                result["rating"] = float(rating_str.split()[0])  # 只要 "4.4" 转换为浮点数

            reviews_ele = tab.ele('@data-reviews', timeout=0.5)
            if reviews_ele:
                result["reviews"] = int(reviews_ele.attr('data-reviews'))  # "42139" 转换为整数
        except Exception:
            pass

        # 提取 BSR
        page_text = tab.ele('tag:body').text
        pattern = r'#([0-9,]+)\s+in\s+([^\n\(]+)'
        matches = re.findall(pattern, page_text)

        if matches:
            # 大类目逻辑不变
            result["main_rank"] = int(matches[0][0].replace(',', ''))
            result["main_category"] = matches[0][1].strip()

            # 【核心逻辑升级】
            bath_rugs_rank = None
            other_sub_ranks_list = []

            if len(matches) > 1:
                for match in matches[1:]:
                    cat_name = match[1].strip()
                    rank_val = int(match[0].replace(',', ''))

                    # 检查是否是核心关注类目
                    if cat_name == "Bath Rugs":
                        bath_rugs_rank = rank_val
                    else:
                        # 其他类目存入 JSON 列表
                        other_sub_ranks_list.append({
                            "category": cat_name,
                            "rank": rank_val
                        })

            result["bath_rugs_rank"] = bath_rugs_rank
            result["other_sub_ranks"] = json.dumps(other_sub_ranks_list)

            result["status"] = "success"
            print(f"[成功] {asin} | 大类: {result['main_rank']} | Bath Rugs排名: {bath_rugs_rank}")
        else:
            print(f"[失败] {asin} | 未找到排名格式")

    except Exception as e:
        print(f"[报错] {asin} | {type(e).__name__}")

    finally:
        tab.close()

    return result


# ================= 4. 数据库写入逻辑 =================
def save_to_db(result_dict):
    if result_dict["status"] != "success":
        return

    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        # 1. 扩充 upsert 逻辑，将静态属性统统存入 products 表
        cursor.execute("""
                       INSERT INTO products (asin, title, brand, material, back_material, item_shape, item_size)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asin) 
            DO
                       UPDATE SET
                           title = COALESCE (EXCLUDED.title, products.title),
                           brand = COALESCE (EXCLUDED.brand, products.brand),
                           material = COALESCE (EXCLUDED.material, products.material),
                           back_material = COALESCE (EXCLUDED.back_material, products.back_material),
                           item_shape = COALESCE (EXCLUDED.item_shape, products.item_shape),
                           item_size = COALESCE (EXCLUDED.item_size, products.item_size);
                       """, (
                           result_dict["asin"],
                           result_dict["title"],
                           result_dict["brand"],
                           result_dict["material"],
                           result_dict["back_material"],
                           result_dict["item_shape"],
                           result_dict["size"]
                       ))

        # 2. 写入历史表，包含核心列和补充列
        cursor.execute("""
                       INSERT INTO bsr_history (asin, main_category, main_rank, bath_rugs_rank, other_sub_ranks, rating,
                                                reviews)
                       VALUES (%s, %s, %s, %s, %s, %s, %s);
                       """, (
                           result_dict["asin"],
                           result_dict["main_category"],
                           result_dict["main_rank"],
                           result_dict["bath_rugs_rank"],  # 核心关注类目
                           result_dict["other_sub_ranks"],  # 其他类目JSON
                           result_dict["rating"],
                           result_dict["reviews"]
                       ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[{result_dict['asin']}] 入库失败: {e}")
    finally:
        cursor.close()
        conn.close()


# ================= 4. 数据库写入逻辑 =================
def save_to_db(result_dict):
    if result_dict.get("status") != "success":
        return

    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        # 1. 扩充 upsert 逻辑，将静态属性统统存入 products 表
        cursor.execute("""
                       INSERT INTO products (asin, title, brand, material, back_material, item_shape, item_size)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asin) 
            DO
                       UPDATE SET
                           title = COALESCE (EXCLUDED.title, products.title),
                           brand = COALESCE (EXCLUDED.brand, products.brand),
                           material = COALESCE (EXCLUDED.material, products.material),
                           back_material = COALESCE (EXCLUDED.back_material, products.back_material),
                           item_shape = COALESCE (EXCLUDED.item_shape, products.item_shape),
                           item_size = COALESCE (EXCLUDED.item_size, products.item_size);
                       """, (
                           result_dict.get("asin"),
                           result_dict.get("title"),
                           result_dict.get("brand"),
                           result_dict.get("material"),
                           result_dict.get("back_material"),
                           result_dict.get("item_shape"),
                           result_dict.get("size")
                       ))

        # 2. 写入历史表 (绝对不能再有 sub_category 了！)
        cursor.execute("""
                       INSERT INTO bsr_history (asin, main_category, main_rank, bath_rugs_rank, other_sub_ranks, rating,
                                                reviews)
                       VALUES (%s, %s, %s, %s, %s, %s, %s);
                       """, (
                           result_dict.get("asin"),
                           result_dict.get("main_category"),
                           result_dict.get("main_rank"),
                           result_dict.get("bath_rugs_rank"),  # 写入核心关注的 Bath Rugs 排名
                           result_dict.get("other_sub_ranks"),  # 写入其他的长尾类目 JSON
                           result_dict.get("rating"),
                           result_dict.get("reviews")
                       ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[{result_dict.get('asin')}] 入库失败: {e}")
    finally:
        cursor.close()
        conn.close()

# ================= 5. 主程序 =================
def main():
    input_file = r'data/input_asins.xlsx'
    if not os.path.exists(input_file):
        print("找不到输入文件！")
        return

    df = pd.read_excel(input_file)
    asins_list = df['ASIN'].dropna().astype(str).tolist()

    print(f"准备抓取并入库 {len(asins_list)} 个 ASIN...")
    browser = setup_browser()
    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_and_clean_bsr, asin, browser): asin for asin in asins_list}

            for future in as_completed(futures):
                result = future.result()
                # 抓取完一条，立刻存入数据库
                save_to_db(result)

        end_time = time.time()
        print(f"\n🎉 抓取及入库全部完成！耗时: {end_time - start_time:.2f} 秒")

    finally:
        browser.quit()


if __name__ == '__main__':
    main()
import os
import re
import time
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import ChromiumOptions, ChromiumPage
import json
import argparse

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
def setup_browser(headless=True):
    co = ChromiumOptions()
    co.headless(headless)  # 根据参数决定是否开启无头模式
    co.mute(True)
    if headless:
        co.no_imgs(True)  # 无头模式下才禁用图片，加快速度

    co.set_user_data_path(r'./bot_data')
    co.set_argument('--lang=en-US')
    co.set_user_agent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return ChromiumPage(co)


# ================= 3. 数据清洗与抓取逻辑 =================
def fetch_and_clean_bsr(asin, page, headless=True):
    url = f"https://www.amazon.com/dp/{asin}?language=en_US"
    tab = page.new_tab(url)

    result = {
        "asin": asin,
        "title": None, "brand": None,
        "material": None, "back_material": None, "item_shape": None, "size": None,
        "main_category": None, "main_rank": None,
        "bath_rugs_rank": None, "other_sub_ranks": "[]",
        "rating": None, "reviews": None,
        "status": "failed"
    }

    try:
        tab.wait.load_start()
        # 自动点击“继续购物”按钮（如果有反爬拦截）
        bot_btn = tab.ele('text:Continue shopping', timeout=0.5)
        if bot_btn:
            bot_btn.click()
            tab.wait(2)

        # 1. 提取标题
        try:
            title_ele = tab.ele('#productTitle', timeout=1)
            if title_ele:
                result["title"] = title_ele.text.strip()
            else:
                meta_content = tab.ele('tag:meta@name=title').attr('content')
                if meta_content:
                    result["title"] = meta_content.replace("Amazon.com: ", "").split(" : ")[0].strip()
        except:
            pass

        tab.scroll.to_half()
        tab.wait(0.5)
        tab.scroll.to_bottom()
        tab.wait(0.5)

        # 2. 批量提取表格属性 (XPath 精准定位)
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
                xpath_str = f'xpath://th[normalize-space(text())="{label}"]'
                th_ele = tab.ele(xpath_str, timeout=0.2)
                if th_ele and not result[key]:
                    result[key] = th_ele.parent('tag:tr').ele('tag:td').text.strip()
            except:
                continue

        # 3. 提取评价指标
        try:
            rating_ele = tab.ele('@data-rating', timeout=0.5)
            if rating_ele:
                result["rating"] = float(rating_ele.attr('data-rating').split()[0])

            reviews_ele = tab.ele('@data-reviews', timeout=0.5)
            if reviews_ele:
                result["reviews"] = int(reviews_ele.attr('data-reviews'))
        except:
            pass

        # 4. 提取 BSR 排名
        page_text = tab.ele('tag:body').text
        pattern = r'#([0-9,]+)\s+in\s+([^\n\(]+)'
        matches = re.findall(pattern, page_text)

        if matches:
            result["main_rank"] = int(matches[0][0].replace(',', ''))
            result["main_category"] = matches[0][1].strip()

            other_sub_ranks_list = []
            if len(matches) > 1:
                for match in matches[1:]:
                    cat_name = match[1].strip()
                    rank_val = int(match[0].replace(',', ''))
                    if cat_name == "Bath Rugs":
                        result["bath_rugs_rank"] = rank_val
                    else:
                        other_sub_ranks_list.append({"category": cat_name, "rank": rank_val})

            result["other_sub_ranks"] = json.dumps(other_sub_ranks_list)
            result["status"] = "success"
            print(f"[成功] {asin} | 大类: {result['main_rank']} | Bath Rugs排名: {result['bath_rugs_rank']}")
        else:
            print(f"[失败] {asin} | 未找到排名格式。正在截图留存...")
            if not os.path.exists('debug'): os.makedirs('debug')
            tab.get_screenshot(path=f'debug/error_{asin}_{int(time.time())}.jpg')

    except Exception as e:
        print(f"[报错] {asin} | {type(e).__name__}")

    finally:
        # 调试模式下等待，方便人工观察
        if not headless:
            print(f"🕒 [调试模式] {asin} 抓取完毕，等待 60 秒关闭页面...")
            tab.wait(60)
        tab.close()

    return result


# ================= 4. 数据库写入逻辑 =================
def save_to_db(result_dict):
    if result_dict.get("status") != "success":
        return

    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        # 1. 插入/更新产品基础信息
        cursor.execute("""
                       INSERT INTO products (asin, title, brand, material, back_material, item_shape, item_size)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asin) DO
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

        # 2. 插入 BSR 历史记录
        cursor.execute("""
                       INSERT INTO bsr_history (asin, main_category, main_rank, bath_rugs_rank, other_sub_ranks, rating,
                                                reviews)
                       VALUES (%s, %s, %s, %s, %s, %s, %s);
                       """, (
                           result_dict.get("asin"),
                           result_dict.get("main_category"),
                           result_dict.get("main_rank"),
                           result_dict.get("bath_rugs_rank"),
                           result_dict.get("other_sub_ranks"),
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
    parser = argparse.ArgumentParser(description="Amazon BSR Tracker Debug Options")
    parser.add_argument('--debug', action='store_true', help='开启调试模式：显示浏览器窗口且不关屏')
    parser.add_argument('--limit', type=int, default=None, help='限制运行的 ASIN 数量')
    args = parser.parse_args()

    # 数据库预检
    print("🔍 正在预检数据库连接...")
    check_conn = get_db_connection()
    if not check_conn:
        print("🛑 数据库连接失败，请检查 .env 配置。")
        return
    check_conn.close()
    print("✅ 数据库连接正常。")

    input_file = r'data/input_asins.xlsx'
    if not os.path.exists(input_file):
        print("找不到输入文件！")
        return

    df = pd.read_excel(input_file)
    asins_list = df['ASIN'].dropna().astype(str).tolist()

    if args.limit:
        print(f"⚠️ [调试] 仅测试前 {args.limit} 个 ASIN")
        asins_list = asins_list[:args.limit]

    headless_mode = not args.debug
    if args.debug:
        print("🔍 [调试] 以“有头模式”启动，每条数据将停留 60 秒。")

    print(f"准备处理 {len(asins_list)} 个 ASIN...")
    browser = setup_browser(headless=headless_mode)
    start_time = time.time()

    try:
        # 调试模式建议单线程运行，方便观察
        workers = 10 if headless_mode else 1
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # 这里的参数 headless_mode 成功传入抓取函数
            futures = {executor.submit(fetch_and_clean_bsr, asin, browser, headless_mode): asin for asin in asins_list}
            for future in as_completed(futures):
                save_to_db(future.result())

        print(f"\n🎉 任务执行完毕！总耗时: {time.time() - start_time:.2f} 秒")

    finally:
        browser.quit()


if __name__ == '__main__':
    main()
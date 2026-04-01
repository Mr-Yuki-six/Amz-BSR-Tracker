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
from tqdm import tqdm

# 加载 .env 文件中的敏感配置
load_dotenv()


# ================= 0. 配置文件加载（含自动脱敏逻辑） =================
def load_config():
    """
    加载配置文件并自动过滤 // 注释。
    优先读取 config.json，若不存在则读取 config.example.json。
    """
    config_path = 'config.json'
    if not os.path.exists(config_path):
        config_path = 'config.example.json'

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 使用正则表达式去除 // 及其后面的所有内容
                clean_content = re.sub(r'//.*', '', content)
                return json.loads(clean_content)
        except Exception as e:
            print(f"⚠️ 配置文件解析失败: {e}")

    # 默认保底配置：target_category 默认为 None，开启自动捕获模式
    return {
        "target_category": None,
        "max_workers": 5,
        "debug_wait_time": 60,
        "scroll_steps": 2
    }


GLOBAL_CONFIG = load_config()


# ================= 1. 数据库连接配置 =================
def get_db_connection():
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
    co.headless(headless)
    co.mute(True)
    # 根据配置决定无头模式下是否禁用图片
    if headless and GLOBAL_CONFIG.get("headless_img_disabled", True):
        co.no_imgs(True)

    co.set_user_data_path(r'./bot_data')
    co.set_argument('--lang=en-US')
    co.set_user_agent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return ChromiumPage(co)


# ================= 3. 数据清洗与抓取逻辑 =================
def fetch_and_clean_bsr(asin, page, headless=True):
    # 从配置获取目标类目（可能为 None）
    target_cat = GLOBAL_CONFIG.get("target_category")
    url = f"https://www.amazon.com/dp/{asin}?language=en_US"
    tab = page.new_tab(url)

    result = {
        "asin": asin,
        "title": None, "brand": None,
        "material": None, "back_material": None, "item_shape": None, "size": None,
        "main_category": None, "main_rank": None,
        "focus_category_rank": None, "other_sub_ranks": "[]",
        "rating": None, "reviews": None,
        "status": "failed"
    }

    try:
        tab.wait.load_start()
        # 自动点击“继续购物”按钮
        if tab.ele('text:Continue shopping', timeout=0.5):
            tab.ele('text:Continue shopping').click()
            tab.wait(1.5)

        # 1. 提取标题
        title_ele = tab.ele('#productTitle', timeout=1)
        if title_ele:
            result["title"] = title_ele.text.strip()

        # 2. 模拟滚动触发加载
        steps = GLOBAL_CONFIG.get("scroll_steps", 2)
        for _ in range(steps):
            tab.scroll.down(600)
            tab.wait(0.5)

        # 3. 批量提取表格属性 (XPath 精准定位)
        attr_map = {
            "Brand": "brand",
            "Brand Name": "brand",
            "Material Type": "material",
            "Back Material Type": "back_material",
            "Item Shape": "item_shape",
            "Size": "size"
        }

        for label, key in attr_map.items():
            try:
                xpath_str = f'xpath://th[normalize-space(text())="{label}"]'
                th_ele = tab.ele(xpath_str, timeout=0.2)
                if th_ele and not result[key]:
                    result[key] = th_ele.parent('tag:tr').ele('tag:td').text.strip()
            except:
                continue

        # 4. 提取评价指标
        try:
            rating_ele = tab.ele('@data-rating', timeout=0.5)
            if rating_ele:
                result["rating"] = float(rating_ele.attr('data-rating').split()[0])
            reviews_ele = tab.ele('@data-reviews', timeout=0.5)
            if reviews_ele:
                result["reviews"] = int(reviews_ele.attr('data-reviews'))
        except:
            pass

        # 5. 提取 BSR 排名
        page_text = tab.ele('tag:body').text
        matches = re.findall(r'#([0-9,]+)\s+in\s+([^\n\(]+)', page_text)

        if matches:
            # 提取大类排名
            result["main_rank"] = int(matches[0][0].replace(',', ''))
            result["main_category"] = matches[0][1].strip()

            other_sub_ranks_list = []
            if len(matches) > 1:
                # 遍历所有捕捉到的小类目
                for match in matches[1:]:
                    cat_name = match[1].strip()
                    rank_val = int(match[0].replace(',', ''))

                    # 匹配逻辑：
                    # 如果用户指定了 target_category 且匹配成功
                    if target_cat and cat_name == target_cat:
                        result["focus_category_rank"] = rank_val
                    else:
                        other_sub_ranks_list.append({"category": cat_name, "rank": rank_val})

                # 【核心改进】：兜底逻辑
                # 如果 focus_category_rank 依然为空（即：用户没设 target 或者 设了但页面没对上）
                # 且抓到了其他小类目排名，则自动取第一个小类目作为焦点排名
                if result["focus_category_rank"] is None and other_sub_ranks_list:
                    # 弹出第一个作为焦点
                    auto_cat = other_sub_ranks_list.pop(0)
                    result["focus_category_rank"] = auto_cat["rank"]
                    display_cat = auto_cat["category"]
                else:
                    display_cat = target_cat if target_cat else "未发现小类"

            result["other_sub_ranks"] = json.dumps(other_sub_ranks_list)
            result["status"] = "success"

            # 动态打印日志
            print(f"[成功] {asin} | 大类: {result['main_rank']} | {display_cat}排名: {result['focus_category_rank']}")
        else:
            print(f"[失败] {asin} | 未找到排名。")
            if GLOBAL_CONFIG.get("save_error_screenshot", True):
                if not os.path.exists('debug'): os.makedirs('debug')
                tab.get_screenshot(path=f'debug/error_{asin}_{int(time.time())}.jpg')

    except Exception as e:
        print(f"[报错] {asin} | {e}")

    finally:
        if not headless:
            wait_time = GLOBAL_CONFIG.get("debug_wait_time", 60)
            print(f"🕒 [调试] {asin} 完毕，停留 {wait_time}s...")
            tab.wait(wait_time)
        tab.close()

    return result


# ================= 4. 数据库写入逻辑 =================
def save_to_db(result_dict):
    if result_dict.get("status") != "success": return
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        # 1. 产品基础信息 (UPSERT)
        cursor.execute("""
                       INSERT INTO products (asin, title, brand, material, back_material, item_shape, item_size)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asin) DO
                       UPDATE
                           SET
                               title = COALESCE (EXCLUDED.title, products.title),
                           brand = COALESCE (EXCLUDED.brand, products.brand),
                           material = COALESCE (EXCLUDED.material, products.material);
                       """, (result_dict["asin"], result_dict["title"], result_dict["brand"],
                             result_dict["material"], result_dict["back_material"],
                             result_dict["item_shape"], result_dict["size"]))

        # 2. 写入历史表
        cursor.execute("""
                       INSERT INTO bsr_history (asin, main_category, main_rank, focus_category_rank, other_sub_ranks,
                                                rating, reviews)
                       VALUES (%s, %s, %s, %s, %s, %s, %s);
                       """, (result_dict["asin"], result_dict["main_category"], result_dict["main_rank"],
                             result_dict["focus_category_rank"], result_dict["other_sub_ranks"],
                             result_dict["rating"], result_dict["reviews"]))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[{result_dict['asin']}] 入库失败: {e}")
    finally:
        cursor.close()
        conn.close()


# ================= 5. 主程序 =================
def main():
    parser = argparse.ArgumentParser(description="Amazon BSR Tracker")
    parser.add_argument('--debug', action='store_true', help='显示窗口调试')
    parser.add_argument('--limit', type=int, default=None, help='限额测试')
    args = parser.parse_args()

    print("🔍 预检数据库...")
    check = get_db_connection()
    if not check: return
    check.close()

    input_file = r'data/input_asins.xlsx'
    if not os.path.exists(input_file):
        print("❌ 找不到输入文件 data/input_asins.xlsx")
        return

    asins_list = pd.read_excel(input_file)['ASIN'].dropna().astype(str).tolist()
    if args.limit: asins_list = asins_list[:args.limit]

    total_count = len(asins_list)
    success_count = 0
    failed_count = 0

    headless_mode = not args.debug
    browser = setup_browser(headless=headless_mode)
    workers = GLOBAL_CONFIG.get("max_workers", 5) if headless_mode else 1

    print(f"🚀 开始处理 {total_count} 个 ASIN (线程数: {workers})...")
    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch_and_clean_bsr, asin, browser, headless_mode): asin for asin in asins_list}

            with tqdm(total=total_count, desc="📊 抓取进度", unit="asin",
                      bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]') as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    if result.get("status") == "success":
                        success_count += 1
                        save_to_db(result)
                    else:
                        failed_count += 1
                    pbar.update(1)

        end_time = time.time()
        duration = end_time - start_time
        print("\n" + "=" * 50)
        print("🚩 任务汇总报告")
        print(f"⏱️  总耗时: {duration:.2f} 秒")
        print(f"✅ 抓取成功: {success_count}")
        print(f"❌ 抓取失败: {failed_count}")
        print("=" * 50 + "\n")

    finally:
        browser.quit()


if __name__ == '__main__':
    main()
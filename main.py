import time
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import ChromiumOptions, ChromiumPage
import os
import re


# # ================= 1. 浏览器基础配置 =================
# def setup_browser():
#     co = ChromiumOptions()
#     co.headless(False)
#     co.mute(True)
#
#     # 【改动 1】删除无痕模式 co.incognito(True)
#
#     # 【改动 2】为爬虫指定一个专属的缓存数据目录！(它会在你的项目里自动生成一个 bot_data 文件夹)
#     co.set_user_data_path(r'./bot_data')
#
#     co.set_argument('--lang=en-US')
#     co.set_user_agent(
#         'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
#
#     page = ChromiumPage(co)
#     return page

# ================= 1. 浏览器基础配置 =================
def setup_browser():
    co = ChromiumOptions()
    co.headless(True)
    co.mute(True)

    # 【提速 1】重新开启拦截图片！提速核心！
    co.no_imgs(True)

    co.set_user_data_path(r'./bot_data')
    co.set_argument('--lang=en-US')
    co.set_user_agent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    page = ChromiumPage(co)
    return page


# ================= 2. 单个网页的抓取逻辑 =================
def fetch_bsr(asin, page):
    url = f"https://www.amazon.com/dp/{asin}?language=en_US"
    tab = page.new_tab(url)

    try:
        # 【提速 2】去掉死等 2 秒，改为等待页面基础元素开始加载
        tab.wait.load_start()

        # 【提速 3】将验证拦截的寻找时间缩短为 0.5 秒。没有拦截就光速放行
        bot_btn = tab.ele('text:Continue shopping', timeout=0.1)
        if bot_btn:
            bot_btn.click()
            tab.wait(2)

        # 加快向下滚动的节奏
        tab.scroll.to_half()
        tab.wait(0.5)
        tab.scroll.to_bottom()
        tab.wait(0.5)

        page_text = tab.ele('tag:body').text
        pattern = r'#([0-9,]+)\s+in\s+([^\n\(]+)'
        matches = re.findall(pattern, page_text)

        if matches:
            main_rank = f"#{matches[0][0]} in {matches[0][1].strip()}"
            sub_rank = ""
            if len(matches) > 1:
                sub_rank = f" | #{matches[1][0]} in {matches[1][1].strip()}"

            final_bsr = main_rank + sub_rank
            print(f"[成功] {asin} | 排名: {final_bsr}")
            return {"ASIN": asin, "BSR": final_bsr, "状态": "成功"}

        else:
            print(f"[失败] {asin} | 没找到格式。已截图。")
            tab.get_screenshot(path=f'error_{asin}.jpg')
            return {"ASIN": asin, "BSR": "未找到排名", "状态": "失败"}

    except Exception as e:
        print(f"[报错] {asin} | 具体报错: {type(e).__name__} - {str(e)}")
        return {"ASIN": asin, "BSR": "抓取报错", "状态": "失败"}

    finally:
        tab.close()


# ================= 3. 主程序逻辑 =================
def main():
    input_file = r'data/input_asins.xlsx'
    if not os.path.exists(input_file):
        print(f"找不到输入文件: {input_file}")
        return

    df = pd.read_excel(input_file)
    asins_list = df['ASIN'].dropna().astype(str).tolist()

    print(f"成功读取 {len(asins_list)} 个 ASIN。正在启动浏览器引擎...")
    browser = setup_browser()
    results = []

    start_time = time.time()

    try:
        # 【修改点】把核心抓取逻辑放进 try 块里
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_bsr, asin, browser): asin for asin in asins_list}
            for future in as_completed(futures):
                results.append(future.result())

        # 整理结果并保存
        print("正在合并数据并导出结果...")
        results_df = pd.DataFrame(results)
        final_df = pd.merge(df, results_df, on="ASIN", how="left")

        current_time = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = f"data/results/bsr_report_{current_time}.xlsx"
        final_df.to_excel(output_file, index=False)

        end_time = time.time()
        print(f"\n🎉 全部任务执行完毕！耗时: {end_time - start_time:.2f} 秒")
        print(f"📊 报告已保存至: {output_file}")

    finally:
        # 【安全气囊】无论上面代码是顺利执行完，还是你中途按 Ctrl+C 强退，这句一定会执行！
        print("正在清理并关闭浏览器引擎...")
        browser.quit()


if __name__ == '__main__':
    main()
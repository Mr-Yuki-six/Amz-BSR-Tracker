import time
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import ChromiumOptions, ChromiumPage
import os


# ================= 1. 浏览器基础配置 =================
def setup_browser():
    co = ChromiumOptions()
    co.headless(True)  # 开启无头模式
    co.no_imgs(True)  # 拦截图片加载，极大地提升网页加载速度
    co.mute(True)  # 静音

    # 反检测优化：设置一个常见的 User-Agent
    co.set_user_agent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    page = ChromiumPage(co)
    return page


# ================= 2. 单个网页的抓取逻辑 =================
def fetch_bsr(asin, page):
    """
    处理单个 ASIN，提取 BSR
    """
    # 拼接亚马逊的短链接
    url = f"https://www.amazon.com/dp/{asin}"
    tab = page.new_tab(url)

    try:
        # 等待页面加载（寻找 BSR 关键字）
        tab.wait.ele_loaded('text:Best Sellers Rank', timeout=10)

        # 提取 BSR 数据（根据亚马逊页面结构，BSR 通常在包含该文本的父节点中）
        bsr_element = tab.ele('text:Best Sellers Rank').parent(2).text
        bsr_data = bsr_element.replace('\n', ' ').strip()

        print(f"[成功] {asin} | 数据: {bsr_data[:30]}...")
        return {"ASIN": asin, "BSR": bsr_data, "状态": "成功"}

    except Exception as e:
        print(f"[超时/异常] {asin} | 可能无 BSR 或遭遇反爬")
        return {"ASIN": asin, "BSR": "未抓取到", "状态": "失败"}

    finally:
        tab.close()  # 极其重要：释放内存


# ================= 3. 主程序逻辑 =================
def main():
    # 配置文件路径
    input_file = r'data/input_asins.xlsx'

    # 检查文件是否存在
    if not os.path.exists(input_file):
        print(f"找不到输入文件: {input_file}，请确保路径正确且表格存在。")
        return

    print("正在读取 Excel 文件...")
    # 假设你的表格里有一列的名字叫 "ASIN"
    df = pd.read_excel(input_file)
    asins_list = df['ASIN'].dropna().astype(str).tolist()

    print(f"成功读取 {len(asins_list)} 个 ASIN。正在启动浏览器引擎...")
    browser = setup_browser()
    results = []

    start_time = time.time()
    print("开始多线程抓取 (并发数: 4)...")

    # 启动线程池
    with ThreadPoolExecutor(max_workers=4) as executor:
        # 提交任务
        futures = {executor.submit(fetch_bsr, asin, browser): asin for asin in asins_list}

        # 收集结果
        for future in as_completed(futures):
            results.append(future.result())

    browser.quit()

    # 整理结果并保存
    print("正在合并数据并导出结果...")
    results_df = pd.DataFrame(results)

    # 将抓取结果与原始表格按 ASIN 合并（保留你原表里的其他备注信息）
    final_df = pd.merge(df, results_df, on="ASIN", how="left")

    # 生成带时间戳的文件名
    current_time = datetime.now().strftime("%Y%m%d_%H%M")
    output_file = f"data/results/bsr_report_{current_time}.xlsx"

    # 导出到结果文件夹
    final_df.to_excel(output_file, index=False)

    end_time = time.time()
    print(f"\n🎉 全部任务执行完毕！耗时: {end_time - start_time:.2f} 秒")
    print(f"📊 报告已保存至: {output_file}")


if __name__ == '__main__':
    main()
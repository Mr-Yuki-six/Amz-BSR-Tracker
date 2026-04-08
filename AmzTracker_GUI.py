import os
import re
import time
import json
import random
import threading
import pandas as pd
import psycopg2
import schedule
import customtkinter as ctk
from tkinter import filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import ChromiumOptions, ChromiumPage

# ================= 1. 配置管理器 =================
CONFIG_FILE = 'config.json'


def load_config():
    default_config = {
        # --- 核心与爬虫配置 ---
        "target_category": "",
        "max_workers": 5,
        "retry_times": 3,
        "scroll_steps": 3,
        "wait_before_action": 1.0,
        "debug_wait_time": 60,
        "save_error_screenshot": True,
        "headless_img_disabled": True,
        "debug_mode": False,
        # --- 数据库配置 ---
        "db_type": "PostgreSQL",
        "db_host": "localhost",
        "db_port": "5432",
        "db_name": "postgres",
        "db_user": "postgres",
        "db_pass": "",
        "is_first_run": True,
        # --- 看板状态记忆 (V2.5 新增) ---
        "input_mode": "manual",
        "manual_asins": "",
        "selected_file": "",
        "out_db": False,
        "out_excel": True,
        "schedule_time": "14:30"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = re.sub(r'//.*', '', f.read())
                user_config = json.loads(content)
                default_config.update(user_config)
        except Exception:
            pass
    return default_config


def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)


GLOBAL_CONFIG = load_config()


# ================= 2. 核心业务逻辑 =================
def get_db_connection():
    try:
        if GLOBAL_CONFIG.get("db_type") == "PostgreSQL":
            return psycopg2.connect(
                host=GLOBAL_CONFIG.get("db_host"), port=GLOBAL_CONFIG.get("db_port"),
                database=GLOBAL_CONFIG.get("db_name"), user=GLOBAL_CONFIG.get("db_user"),
                password=GLOBAL_CONFIG.get("db_pass")
            )
        return None
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return None


def setup_browser(headless=True):
    co = ChromiumOptions()
    co.set_local_port(random.randint(9300, 9999))
    co.headless(headless)
    co.mute(True)
    if headless and GLOBAL_CONFIG.get("headless_img_disabled", True):
        co.no_imgs(True)
    co.set_user_data_path(r'./bot_data')
    co.set_argument('--lang=en-US')
    co.set_user_agent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

    lock_file = os.path.join('./bot_data', 'SingletonLock')
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
        except:
            pass

    try:
        return ChromiumPage(co)
    except Exception as e:
        raise RuntimeError(
            "检测到后台有残留的 Chrome 进程锁死了缓存文件夹。请在终端运行 'taskkill /f /im chrome.exe' 后重试！")


def fetch_and_clean_bsr(asin, page, headless=True, stop_event=None):
    if stop_event and stop_event.is_set():
        return {"asin": asin, "status": "cancelled"}

    target_cat = GLOBAL_CONFIG.get("target_category")
    retry_times = int(GLOBAL_CONFIG.get("retry_times", 3))
    wait_time = float(GLOBAL_CONFIG.get("wait_before_action", 1.0))

    result = {
        "captured_at": None,
        "asin": asin, "title": None, "brand": None, "material": None, "back_material": None,
        "item_shape": None, "size": None, "main_category": None, "main_rank": None,
        "focus_category_name": None, "focus_category_rank": None, "other_sub_ranks": "[]",
        "rating": None, "reviews": None,
        "star_5_pct": None, "star_4_pct": None, "star_3_pct": None, "star_2_pct": None, "star_1_pct": None,
        "status": "failed"
    }

    tab = page.new_tab()

    for attempt in range(retry_times):
        if stop_event and stop_event.is_set(): break

        try:
            tab.get(f"https://www.amazon.com/dp/{asin}?language=en_US")
            tab.wait.load_start()

            if tab.ele('text:Continue shopping', timeout=0.5):
                tab.ele('text:Continue shopping').click()
                time.sleep(wait_time)

            title_ele = tab.ele('#productTitle', timeout=2)
            if title_ele: result["title"] = title_ele.text.strip()

            for _ in range(int(GLOBAL_CONFIG.get("scroll_steps", 3))):
                if stop_event and stop_event.is_set(): break
                tab.scroll.down(800)
                time.sleep(wait_time * 0.5)

            attr_map = {"Brand": "brand", "Material Type": "material", "Item Shape": "item_shape", "Size": "size"}
            for label, key in attr_map.items():
                try:
                    th_ele = tab.ele(f'xpath://th[normalize-space(text())="{label}"]', timeout=0.2)
                    if th_ele and not result[key]: result[key] = th_ele.parent('tag:tr').ele('tag:td').text.strip()
                except:
                    continue

            try:
                rating_ele = tab.ele('xpath://span[contains(@title, "out of 5 stars")]', timeout=0.5) or tab.ele(
                    'xpath://span[@data-hook="rating-out-of-text"]', timeout=0.5)
                if rating_ele:
                    match = re.search(r'([\d.]+)', rating_ele.text or rating_ele.attr('title'))
                    if match: result["rating"] = float(match.group(1))

                reviews_ele = tab.ele('#acrCustomerReviewText', timeout=0.5) or tab.ele(
                    'xpath://span[@data-hook="total-review-count"]', timeout=0.5)
                if reviews_ele:
                    match = re.search(r'([\d,]+)', reviews_ele.text)
                    if match: result["reviews"] = int(match.group(1).replace(',', ''))

                review_sec = tab.ele('#customerReviews', timeout=1)
                if review_sec:
                    review_sec.scroll.to_see()
                    time.sleep(wait_time)

                hist_table = tab.ele('#histogramTable', timeout=1)
                if hist_table:
                    for row in hist_table.eles('tag:li'):
                        a_tag = row.ele('tag:a')
                        if a_tag:
                            aria_label = a_tag.attr('aria-label')
                            if aria_label:
                                m = re.search(r'(\d+)\s*percent.*?(\d)\s*star', aria_label, re.IGNORECASE)
                                if m:
                                    pct, star = m.groups()
                                    result[f"star_{star}_pct"] = int(pct)
            except:
                pass

            matches = re.findall(r'#([0-9,]+)\s+in\s+([^\n\(]+)', tab.ele('tag:body').text)
            if matches:
                result["main_rank"] = int(matches[0][0].replace(',', ''))
                result["main_category"] = matches[0][1].strip()
                other_sub_ranks_list = []
                if len(matches) > 1:
                    for match in matches[1:]:
                        cat_name, rank_val = match[1].strip(), int(match[0].replace(',', ''))
                        if target_cat and cat_name == target_cat:
                            result["focus_category_rank"] = rank_val
                            result["focus_category_name"] = cat_name
                        else:
                            other_sub_ranks_list.append({"category": cat_name, "rank": rank_val})

                    if result["focus_category_rank"] is None and other_sub_ranks_list:
                        auto_cat = other_sub_ranks_list.pop(0)
                        result["focus_category_rank"] = auto_cat["rank"]
                        result["focus_category_name"] = auto_cat["category"]

                result["other_sub_ranks"] = json.dumps(other_sub_ranks_list)
                result["status"] = "success"
                result["captured_at"] = time.strftime('%Y-%m-%d %H:%M:%S')
                break

        except Exception as e:
            print(f"[报错] {asin} | {e}")
            time.sleep(wait_time)

    if result["status"] == "failed" and GLOBAL_CONFIG.get("save_error_screenshot", True):
        if not os.path.exists('debug'): os.makedirs('debug')
        tab.get_screenshot(path=f'debug/error_{asin}_{int(time.time())}.jpg')

    if not headless and not (stop_event and stop_event.is_set()):
        tab.wait(GLOBAL_CONFIG.get("debug_wait_time", 60))
    tab.close()

    return result


def save_to_db(result_dict):
    conn = get_db_connection()
    if not conn: return False, "数据库连接失败或配置不正确"
    cursor = conn.cursor()
    try:
        cursor.execute("""
                       INSERT INTO products (asin, title, brand, material, item_shape, item_size)
                       VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (asin) DO
                       UPDATE
                       SET
                           title = COALESCE (EXCLUDED.title, products.title), brand = COALESCE (EXCLUDED.brand, products.brand), material = COALESCE (EXCLUDED.material, products.material), item_shape = COALESCE (EXCLUDED.item_shape, products.item_shape), item_size = COALESCE (EXCLUDED.item_size, products.item_size), updated_at = CURRENT_TIMESTAMP;
                       """, (result_dict["asin"], result_dict["title"], result_dict["brand"], result_dict["material"],
                             result_dict["item_shape"], result_dict["size"]))

        cursor.execute("""
                       INSERT INTO bsr_history (asin, main_category, main_rank, focus_category_name,
                                                focus_category_rank, other_sub_ranks, rating, reviews, star_5_pct,
                                                star_4_pct, star_3_pct, star_2_pct, star_1_pct)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                       """, (result_dict["asin"], result_dict["main_category"], result_dict["main_rank"],
                             result_dict["focus_category_name"], result_dict["focus_category_rank"],
                             result_dict["other_sub_ranks"], result_dict["rating"], result_dict["reviews"],
                             result_dict["star_5_pct"], result_dict["star_4_pct"], result_dict["star_3_pct"],
                             result_dict["star_2_pct"], result_dict["star_1_pct"]))
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e).strip()
    finally:
        cursor.close()
        conn.close()


def save_to_excel(result_dict, file_path):
    df = pd.DataFrame([result_dict])
    if os.path.exists(file_path):
        existing_df = pd.read_excel(file_path)
        df = pd.concat([existing_df, df], ignore_index=True)
    df.to_excel(file_path, index=False)


# ================= 3. GUI 界面与调度系统 =================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class BSRTrackerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Amz BSR Tracker V2.5 - Operations Pro")
        self.geometry("750x850")
        self.is_running = False
        self.stop_event = threading.Event()

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=10, fill="both", expand=True)
        self.tab_dashboard = self.tabview.add("📊 抓取看板")
        self.tab_settings = self.tabview.add("⚙️ 高级配置")

        self.build_dashboard_tab()
        self.build_settings_tab()
        self.check_first_run()

        self.scheduler_thread = threading.Thread(target=self.run_schedule, daemon=True)
        self.scheduler_thread.start()

    def check_first_run(self):
        if GLOBAL_CONFIG.get("is_first_run", True):
            def show_welcome():
                msg = (
                    "🎉 首次运行提示\n\n"
                    "为了确保准确抓取目标站点的数据，系统已为您【临时开启 Debug 模式】（显示浏览器窗口）。\n\n"
                    "👉 稍后点击“开始抓取”时，请在弹出的浏览器中，手动修改左上角的【亚马逊配送邮编】（例如：美国站填 10001）。\n\n"
                    "修改完成后关闭浏览器即可。系统会自动记录您的设定，下次重新打开软件时，将恢复默认的后台静默抓取！"
                )
                messagebox.showinfo("环境初始化", msg)

                GLOBAL_CONFIG["is_first_run"] = False
                save_config(GLOBAL_CONFIG)

                if "debug_mode" in self.vars:
                    self.vars["debug_mode"].set(True)

            self.after(500, show_welcome)

    # 核心新增功能：静默保存看板状态
    def silent_save_dashboard_state(self):
        GLOBAL_CONFIG["input_mode"] = self.input_var.get()
        GLOBAL_CONFIG["manual_asins"] = self.textbox_asin.get("1.0", "end").strip()
        if hasattr(self, 'selected_file') and self.selected_file:
            GLOBAL_CONFIG["selected_file"] = self.selected_file
        GLOBAL_CONFIG["out_db"] = self.out_db_var.get()
        GLOBAL_CONFIG["out_excel"] = self.out_excel_var.get()
        GLOBAL_CONFIG["schedule_time"] = self.entry_time.get().strip()
        save_config(GLOBAL_CONFIG)

    def build_dashboard_tab(self):
        frame_in = ctk.CTkFrame(self.tab_dashboard)
        frame_in.pack(pady=5, fill="x")

        # 恢复上次保存的输入模式，默认 manual
        self.input_var = ctk.StringVar(value=GLOBAL_CONFIG.get("input_mode", "manual"))

        ctk.CTkRadioButton(frame_in, text="手动输入 ASIN (每行一个)", variable=self.input_var, value="manual",
                           command=self.toggle_input).pack(anchor="w", padx=20, pady=(10, 5))
        self.textbox_asin = ctk.CTkTextbox(frame_in, height=80)
        self.textbox_asin.insert("1.0", GLOBAL_CONFIG.get("manual_asins", ""))  # 恢复上次输入的 ASIN
        self.textbox_asin.pack(fill="x", padx=20, pady=5)

        file_frame = ctk.CTkFrame(frame_in, fg_color="transparent")
        file_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkRadioButton(file_frame, text="上传本地文件", variable=self.input_var, value="file",
                           command=self.toggle_input).pack(side="left", pady=5)

        # 恢复上次选择的文件路径
        saved_file = GLOBAL_CONFIG.get("selected_file", "")
        display_text = os.path.basename(saved_file) if saved_file and os.path.exists(saved_file) else "未选择文件"
        if saved_file and os.path.exists(saved_file):
            self.selected_file = saved_file

        self.file_path_label = ctk.CTkLabel(file_frame, text=display_text, text_color="gray")
        self.file_path_label.pack(side="left", padx=10)
        self.btn_browse = ctk.CTkButton(file_frame, text="浏览...", width=60, state="disabled",
                                        command=self.browse_file)
        self.btn_browse.pack(side="left")

        self.btn_template = ctk.CTkButton(file_frame, text="下载模板", width=80, fg_color="#2980b9",
                                          command=self.download_template)
        self.btn_template.pack(side="right", padx=10)

        ctk.CTkRadioButton(frame_in, text="读取同目录的 input_asins.xlsx", variable=self.input_var, value="default",
                           command=self.toggle_input).pack(anchor="w", padx=20, pady=(5, 10))

        frame_mid = ctk.CTkFrame(self.tab_dashboard)
        frame_mid.pack(pady=5, fill="x")

        # 恢复数据库和 Excel 的勾选状态
        self.out_db_var = ctk.BooleanVar(value=GLOBAL_CONFIG.get("out_db", False))
        self.out_excel_var = ctk.BooleanVar(value=GLOBAL_CONFIG.get("out_excel", True))
        ctk.CTkCheckBox(frame_mid, text="保存到数据库", variable=self.out_db_var).pack(side="left", padx=20, pady=10)
        ctk.CTkCheckBox(frame_mid, text="导出 xlsx", variable=self.out_excel_var).pack(side="left", padx=10, pady=10)

        timer_frame = ctk.CTkFrame(frame_mid, fg_color="transparent")
        timer_frame.pack(side="right", padx=10, pady=5)
        ctk.CTkLabel(timer_frame, text="每天执行(14:30):").pack(side="left")
        self.entry_time = ctk.CTkEntry(timer_frame, width=60)
        self.entry_time.insert(0, GLOBAL_CONFIG.get("schedule_time", "14:30"))  # 恢复定时时间
        self.entry_time.pack(side="left", padx=5)
        self.btn_schedule = ctk.CTkButton(timer_frame, text="启用定时", width=80, fg_color="orange",
                                          command=self.toggle_schedule)
        self.btn_schedule.pack(side="left")

        btn_frame = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        btn_frame.pack(pady=10, fill="x")
        self.btn_run = ctk.CTkButton(btn_frame, text="▶ 立即开始抓取", height=40, font=("Arial", 16, "bold"),
                                     fg_color="green", command=self.prepare_and_start)
        self.btn_run.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.btn_stop = ctk.CTkButton(btn_frame, text="⏹ 停止", height=40, width=80, font=("Arial", 16, "bold"),
                                      fg_color="#c0392b", state="disabled", command=self.stop_scraping)
        self.btn_stop.pack(side="right")

        self.log_box = ctk.CTkTextbox(self.tab_dashboard, state="disabled")
        self.log_box.pack(pady=5, fill="both", expand=True)

        # 初始化时触发一次模式判断，锁定对应输入框
        self.toggle_input()

    def build_settings_tab(self):
        scroll_frame = ctk.CTkScrollableFrame(self.tab_settings)
        scroll_frame.pack(fill="both", expand=True)

        f_core = ctk.CTkFrame(scroll_frame)
        f_core.pack(pady=5, fill="x", padx=5)
        ctk.CTkLabel(f_core, text="1. 核心业务与性能", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=10,
                                                                                        pady=10, sticky="w")

        self.entries = {}

        def add_entry(parent, label_text, key, row, width=200, placeholder=""):
            ctk.CTkLabel(parent, text=label_text).grid(row=row, column=0, padx=10, pady=5, sticky="w")
            entry = ctk.CTkEntry(parent, width=width, placeholder_text=placeholder)
            val = str(GLOBAL_CONFIG.get(key, ""))
            if val:
                entry.insert(0, val)
            entry.grid(row=row, column=1, padx=10, pady=5, sticky="w")
            self.entries[key] = entry

        add_entry(f_core, "核心监控类目 (留空为自动):", "target_category", 1,
                  placeholder="如: Travel & To-Go Drinkware")
        add_entry(f_core, "并发线程数 (3-8):", "max_workers", 2, 80)
        add_entry(f_core, "失败重试次数:", "retry_times", 3, 80)

        f_auto = ctk.CTkFrame(scroll_frame)
        f_auto.pack(pady=5, fill="x", padx=5)
        ctk.CTkLabel(f_auto, text="2. 自动化行为配置", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=10,
                                                                                        pady=10, sticky="w")

        add_entry(f_auto, "页面滚动次数:", "scroll_steps", 1, 80)
        add_entry(f_auto, "操作停顿时间 (秒):", "wait_before_action", 2, 80)
        add_entry(f_auto, "Debug模式页面停留 (秒):", "debug_wait_time", 3, 80)

        f_switches = ctk.CTkFrame(scroll_frame)
        f_switches.pack(pady=5, fill="x", padx=5)
        ctk.CTkLabel(f_switches, text="3. 调试与防御", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=10,
                                                                                        pady=10, sticky="w")

        self.vars = {}

        def add_switch(parent, text, key, row):
            var = ctk.BooleanVar(value=GLOBAL_CONFIG.get(key, False))
            ctk.CTkSwitch(parent, text=text, variable=var).grid(row=row, column=0, padx=10, pady=5, sticky="w")
            self.vars[key] = var

        add_switch(f_switches, "报错时自动截图保存", "save_error_screenshot", 1)
        self.vars["save_error_screenshot"].set(GLOBAL_CONFIG.get("save_error_screenshot", True))

        add_switch(f_switches, "无头模式下禁用图片 (加速)", "headless_img_disabled", 2)
        self.vars["headless_img_disabled"].set(GLOBAL_CONFIG.get("headless_img_disabled", True))

        add_switch(f_switches, "强制开启有头模式 (Debug)", "debug_mode", 3)
        self.vars["debug_mode"].set(GLOBAL_CONFIG.get("debug_mode", False))

        f_db = ctk.CTkFrame(scroll_frame)
        f_db.pack(pady=5, fill="x", padx=5)
        ctk.CTkLabel(f_db, text="4. 数据库连接", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=10, pady=10,
                                                                                  sticky="w")

        ctk.CTkLabel(f_db, text="数据库类型:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.set_dbtype = ctk.CTkOptionMenu(f_db, values=["PostgreSQL", "MySQL", "SQLite"])
        self.set_dbtype.set(GLOBAL_CONFIG.get("db_type", "PostgreSQL"))
        self.set_dbtype.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        add_entry(f_db, "Host IP:", "db_host", 2)
        add_entry(f_db, "Port:", "db_port", 3)
        add_entry(f_db, "DB Name:", "db_name", 4)
        add_entry(f_db, "Username:", "db_user", 5)

        ctk.CTkLabel(f_db, text="Password:").grid(row=6, column=0, padx=10, pady=5, sticky="w")
        self.entry_pass = ctk.CTkEntry(f_db, width=200, show="*")
        self.entry_pass.insert(0, GLOBAL_CONFIG.get("db_pass", ""))
        self.entry_pass.grid(row=6, column=1, padx=10, pady=5, sticky="w")

        ctk.CTkButton(scroll_frame, text="💾 保存所有配置", height=40, command=self.save_settings).pack(pady=20)

    def save_settings(self):
        # 保存设置页面的参数
        for key, entry in self.entries.items():
            val = entry.get().strip()
            if val.isdigit():
                GLOBAL_CONFIG[key] = int(val)
            else:
                try:
                    GLOBAL_CONFIG[key] = float(val)
                except ValueError:
                    GLOBAL_CONFIG[key] = val

        for key, var in self.vars.items():
            GLOBAL_CONFIG[key] = var.get()

        GLOBAL_CONFIG["db_type"] = self.set_dbtype.get()
        GLOBAL_CONFIG["db_pass"] = self.entry_pass.get()

        # 同时保存看板页面的状态
        self.silent_save_dashboard_state()

        messagebox.showinfo("成功", "所有配置与当前面板状态已保存至 config.json，下次抓取即生效！")

    def toggle_input(self):
        mode = self.input_var.get()
        self.btn_browse.configure(state="normal" if mode == "file" else "disabled")
        self.textbox_asin.configure(state="normal" if mode == "manual" else "disabled")

    def browse_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        if filepath:
            self.file_path_label.configure(text=os.path.basename(filepath))
            self.selected_file = filepath

    def download_template(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile="ASIN_Input_Template.xlsx",
            title="保存模板",
            filetypes=[("Excel files", "*.xlsx")]
        )
        if filepath:
            try:
                pd.DataFrame({"ASIN": ["B0BZYCJK89", "B06X6J5266"]}).to_excel(filepath, index=False)
                messagebox.showinfo("成功", f"模板已保存至:\n{filepath}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")

    def log(self, message):
        def update():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, update)

    def toggle_schedule(self):
        # 点击定时器时，自动记忆当前面板的所有选择
        self.silent_save_dashboard_state()

        if self.btn_schedule.cget("text") == "启用定时":
            run_time = self.entry_time.get().strip()
            if not re.match(r"^[0-2][0-9]:[0-5][0-9]$", run_time):
                messagebox.showerror("错误", "时间格式必须为 HH:MM")
                return
            schedule.every().day.at(run_time).do(self.prepare_and_start)
            self.btn_schedule.configure(text=f"已排期", fg_color="gray")
            self.entry_time.configure(state="disabled")
            self.log(f"⏰ 守护进程启动，每日 {run_time} 自动执行。")
        else:
            schedule.clear()
            self.btn_schedule.configure(text="启用定时", fg_color="orange")
            self.entry_time.configure(state="normal")
            self.log("⏰ 定时任务已取消。")

    def run_schedule(self):
        while True:
            schedule.run_pending()
            time.sleep(1)

    def stop_scraping(self):
        if self.is_running:
            self.log("🛑 正在发送停止指令，取消未开始的任务并等待当前页面关闭...")
            self.stop_event.set()
            self.btn_stop.configure(state="disabled", text="停止中...")

    def prepare_and_start(self):
        if self.is_running: return

        # 点击开始按钮时，自动记忆当前面板的所有选择！
        self.silent_save_dashboard_state()

        self.excel_save_path = None
        if self.out_excel_var.get():
            self.excel_save_path = "bsr_output.xlsx"

        self.is_running = True
        self.stop_event.clear()
        self.btn_run.configure(state="disabled", text="抓取中...", fg_color="gray")
        self.btn_stop.configure(state="normal", text="⏹ 停止")
        threading.Thread(target=self.core_scraping_task, daemon=True).start()

    def core_scraping_task(self):
        self.log("🚀 任务初始化...")
        asins = []
        mode = self.input_var.get()

        try:
            if mode == "default":
                if not os.path.exists('input_asins.xlsx'):
                    raise ValueError("找不到同目录下的 input_asins.xlsx！")
                asins = pd.read_excel('input_asins.xlsx')['ASIN'].dropna().astype(str).tolist()
            elif mode == "file":
                if not hasattr(self, 'selected_file'): raise ValueError("请先选择 Excel 文件")
                asins = pd.read_excel(self.selected_file)['ASIN'].dropna().astype(str).tolist()
            elif mode == "manual":
                raw_text = self.textbox_asin.get("1.0", "end").strip()
                asins = [a.strip() for a in raw_text.split('\n') if a.strip()]
                if not asins: raise ValueError("请输入至少一个 ASIN")
        except Exception as e:
            self.log(f"❌ 数据加载失败: {e}")
            self.reset_ui()
            return

        out_db = self.out_db_var.get()
        out_excel = self.out_excel_var.get()
        if not out_db and not out_excel:
            self.log("❌ 请至少选择一种输出方式！")
            self.reset_ui()
            return

        debug_mode = self.vars["debug_mode"].get()
        max_workers = 1 if debug_mode else int(GLOBAL_CONFIG.get("max_workers", 5))

        self.log(f"📦 加载 {len(asins)} 个 ASIN。浏览器启动中 (Debug: {debug_mode}, 并发: {max_workers})...")
        try:
            browser = setup_browser(headless=not debug_mode)
        except Exception as e:
            self.log(f"❌ 浏览器启动失败: {e}")
            self.reset_ui()
            return

        success, failed, cancelled = 0, 0, 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_and_clean_bsr, asin, browser, not debug_mode, self.stop_event): asin for
                       asin in asins}

            for future in as_completed(futures):
                if self.stop_event.is_set():
                    for f in futures: f.cancel()

                try:
                    result = future.result()
                    if result.get("status") == "cancelled":
                        cancelled += 1
                        continue

                    if result.get("status") == "success":
                        db_ok, db_err = True, ""
                        if out_db:
                            db_ok, db_err = save_to_db(result)
                        if out_excel and self.excel_save_path:
                            save_to_excel(result, self.excel_save_path)

                        if db_ok:
                            success += 1
                            display_cat = result.get('focus_category_name') or '未抓取到小类目'
                            self.log(
                                f"✅ [{success + failed}/{len(asins)}] 成功: {result['asin']} -> {display_cat} (#{result['focus_category_rank']})")
                        else:
                            failed += 1
                            self.log(f"⚠️ [{success + failed}/{len(asins)}] DB异常: {result['asin']} | 原因: {db_err}")
                    else:
                        failed += 1
                        self.log(f"❌ [{success + failed}/{len(asins)}] 抓取失败: {result['asin']}")
                except Exception as e:
                    self.log(f"⚠️ 线程异常中断: {e}")

        browser.quit()
        if self.stop_event.is_set():
            self.log(f"🛑 任务已被手动终止！(成功: {success} | 失败: {failed} | 已取消: {cancelled})")
        else:
            self.log(f"🏁 任务结束！(成功: {success} | 失败: {failed})")
        self.reset_ui()

    def reset_ui(self):
        self.is_running = False

        def update():
            self.btn_run.configure(state="normal", text="▶ 立即开始抓取", fg_color="green")
            self.btn_stop.configure(state="disabled", text="⏹ 停止")

        self.after(0, update)


if __name__ == "__main__":
    app = BSRTrackerApp()
    app.mainloop()
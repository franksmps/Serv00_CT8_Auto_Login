# main.py
import os
import json
import asyncio
import random
import requests
from datetime import datetime, timedelta, timezone
from pyppeteer import launch
import aiofiles

# 环境变量：请在运行环境里设置好
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')  # 若多个 chat id 请用逗号分隔

# ----- 时间工具 -----
def format_to_iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def now_beijing() -> datetime:
    return now_utc() + timedelta(hours=8)

# ----- 全局浏览器实例 -----
browser = None

# ----- 延时工具（毫秒） -----
async def delay_time(ms: int):
    await asyncio.sleep(ms / 1000)

# ----- 登录逻辑（支持 Serv00 新/旧页 + CT8） -----
async def login(username: str, password: str, panel: str, screenshot_dir: str = '.') -> (bool, str):
    """
    尝试登录并返回 (is_logged_in, screenshot_path_or_empty)
    会在失败或需要排查时保存截图到 screenshot_dir。
    """
    global browser
    page = None
    serviceName = 'CT8' if 'ct8' in panel.lower() else 'Serv00'
    safe_user = username.replace('/', '_').replace('\\', '_')
    screenshot_path = os.path.join(screenshot_dir, f"screenshot_{serviceName}_{safe_user}.png")

    try:
        if not browser:
            # 这里 headless 可设为 False 排查问题时可见浏览器
            browser = await launch(headless=True, args=[
                '--no-sandbox', '--disable-setuid-sandbox',
                '--disable-dev-shm-usage', '--disable-gpu'
            ])

        page = await browser.newPage()
        url = f'https://{panel}/login/?next=/'
        await page.goto(url, {"waitUntil": "networkidle2", "timeout": 30000})

        # 等待可能存在的用户名/密码输入框（多候选选择器）
        username_selectors = [
            'input[name="username"]', 'input[name="login"]', '#id_username', 'input[type="text"]'
        ]
        password_selectors = [
            'input[name="password"]', '#id_password', 'input[type="password"]'
        ]
        login_btn_selectors = [
            'button[type="submit"]', 'input[type="submit"]', 'button.login-button', 'button.btn'
        ]

        # 等待 username/password 可见（更宽松的等待策略）
        found_username = None
        found_password = None
        for sel in username_selectors:
            try:
                await page.waitForSelector(sel, {'visible': True, 'timeout': 10000})
                found_username = sel
                break
            except:
                continue

        for sel in password_selectors:
            try:
                await page.waitForSelector(sel, {'visible': True, 'timeout': 10000})
                found_password = sel
                break
            except:
                continue

        if not (found_username and found_password):
            # 保存截图供排查
            try:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
            except:
                pass
            raise Exception("找不到用户名或密码输入框（可能页面结构改变或被 JS 动态渲染）")

        # 输入用户名/密码（清空并输入）
        try:
            await page.click(found_username)
            await page.evaluate('(sel) => document.querySelector(sel).value = ""', found_username)
            await page.type(found_username, username, {'delay': 50})
        except Exception:
            # 后备：直接执行 JS 填充
            await page.evaluate('(sel, val) => { const el = document.querySelector(sel); if(el){ el.focus(); el.value = val; el.dispatchEvent(new Event("input", {bubbles:true})); }}', found_username, username)

        try:
            await page.click(found_password)
            await page.evaluate('(sel) => document.querySelector(sel).value = ""', found_password)
            await page.type(found_password, password, {'delay': 50})
        except Exception:
            await page.evaluate('(sel, val) => { const el = document.querySelector(sel); if(el){ el.focus(); el.value = val; el.dispatchEvent(new Event("input", {bubbles:true})); }}', found_password, password)

        # 等待并找到登录按钮
        login_button = None
        for sel in login_btn_selectors:
            try:
                login_button = await page.waitForSelector(sel, {'visible': True, 'timeout': 8000})
                if login_button:
                    break
            except:
                continue

        # 如果没找到按钮，尝试查找包含登录文字的按钮（多语言）
        if not login_button:
            possible_btns = await page.querySelectorAll('button, a, input[type="button"], input[type="submit"]')
            for b in possible_btns:
                try:
                    text = (await page.evaluate('(el) => el.innerText || el.value || ""', b)).strip().lower()
                    if any(k in text for k in ['login', 'sign in', 'sign-in', 'sign_in', 'ZALOGUJ SIĘ', 'signin', '登 录', '登录']):
                        login_button = b
                        break
                except:
                    continue

        if not login_button:
            # 截图并报错
            try:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
            except:
                pass
            raise Exception("找不到登录按钮（可能被隐藏或页面结构改变）")

        # 滚动并尝试点击（允许重试）
        try:
            await page.evaluate('(el) => el.scrollIntoView({behavior:"auto", block:"center"})', login_button)
        except:
            pass
        await asyncio.sleep(0.6)

        clicked = False
        for attempt in range(2):
            try:
                await login_button.click()
                clicked = True
                break
            except Exception:
                await asyncio.sleep(1)
                # 尝试用 JS 点击
                try:
                    await page.evaluate('(el) => el.click()', login_button)
                    clicked = True
                    break
                except:
                    continue

        if not clicked:
            try:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
            except:
                pass
            raise Exception("无法点击登录按钮（被覆盖/不可见/非 HTMLElement）")

        # 等待导航或网络空闲；如果没有导航，也继续检查页面内容
        try:
            await page.waitForNavigation({"waitUntil": "networkidle2", "timeout": 15000})
        except:
            # 有的 SPA 不会导航，允许继续
            await asyncio.sleep(1)

        # 读取页面纯文本判断状态
        try:
            page_text = await page.evaluate('() => document.body.innerText')
        except:
            page_text = ""

        # 如果页面提示验证码或验证，则保存截图并返回失败
        lowered = page_text.lower()
        if "captcha" in lowered or "verify" in lowered or "验证码" in lowered or "请验证" in lowered:
            try:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
            except:
                pass
            raise Exception("页面要求额外验证（验证码/二次验证）")

        # 判断登录成功的多种策略
        is_logged_in = False
        try:
            is_logged_in = await page.evaluate('''() => {
                if (document.querySelector('a[href="/logout/"]')) return true;
                const t = document.body.innerText || '';
                if (t.includes("Dashboard") || t.includes("Welcome") || t.includes("登出") || t.includes("Logout")) return true;
                return false;
            }''')
        except:
            is_logged_in = False

        # 进一步验证 panel 首页可访问性
        if is_logged_in:
            try:
                await page.goto(f'https://{panel}/panel/', {"waitUntil": "networkidle2", "timeout": 15000})
                html = await page.content()
                if any(k in html for k in ["Access denied", "Denied", "Error", "Forbidden"]):
                    is_logged_in = False
            except:
                # 如果访问失败则认为不可靠
                is_logged_in = False

        # 登录失败则保留截图；登录成功则删除旧截图（如果有）
        if is_logged_in:
            if os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except:
                    pass
            return True, ""
        else:
            # 保存截图供排查
            try:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
            except:
                pass
            return False, screenshot_path

    except Exception as e:
        print(f"{serviceName}账号 {username} 登录时出现错误: {e}")
        # 确保截图已保存
        try:
            if page:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
        except:
            pass
        return False, screenshot_path

    finally:
        if page:
            try:
                await page.close()
            except:
                pass

# ----- 关闭浏览器 -----
async def shutdown_browser():
    global browser
    if browser:
        try:
            await browser.close()
        except:
            pass
        browser = None

# ----- Telegram: 发送文本（自动分片） -----
def send_telegram_text(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，跳过发送")
        return

    # 支持多个 chat_id（逗号分隔）
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(',') if c.strip()]

    MAX_LEN = 3500  # 留点余量
    parts = []
    if len(text) <= MAX_LEN:
        parts = [text]
    else:
        # 简单分段：按换行分割
        lines = text.splitlines(keepends=True)
        cur = ""
        for ln in lines:
            if len(cur) + len(ln) > MAX_LEN:
                parts.append(cur)
                cur = ln
            else:
                cur += ln
        if cur:
            parts.append(cur)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    headers = {'Content-Type': 'application/json'}
    for part in parts:
        for chat in chat_ids:
            payload = {
                'chat_id': chat,
                'text': part,
                'parse_mode': 'Markdown'
            }
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code != 200:
                    print("发送 Telegram 文本失败:", resp.text)
            except Exception as e:
                print("发送 Telegram 文本异常:", e)

# ----- Telegram: 发送截图文件 -----
def send_telegram_photo(photo_path: str, caption: str = ""):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，跳过发送图片")
        return
    if not os.path.exists(photo_path):
        print("截图不存在，跳过发送图片:", photo_path)
        return

    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(',') if c.strip()]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    for chat in chat_ids:
        try:
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data = {'chat_id': chat, 'caption': caption, 'parse_mode': 'Markdown'}
                resp = requests.post(url, data=data, files=files, timeout=30)
            if resp.status_code != 200:
                print("发送图片到 Telegram 失败:", resp.text)
        except Exception as e:
            print("发送图片到 Telegram 出错:", e)

# ----- 主流程 -----
async def main():
    # 读取 accounts.json
    try:
        async with aiofiles.open('accounts.json', mode='r', encoding='utf-8') as f:
            accounts_raw = await f.read()
        accounts = json.loads(accounts_raw)
    except Exception as e:
        print("读取 accounts.json 出错:", e)
        return

    report = []
    header = "📊 *Serv00 & CT8 登录状态报告*\n"
    header += "━━━━━━━━━━━━━━━━━━━━\n"
    report.append(header)

    for account in accounts:
        username = account.get('username')
        password = account.get('password')
        panel = account.get('panel')
        if not (username and password and panel):
            print("账户信息不完整，跳过：", account)
            continue

        print(f"开始登录: {panel} / {username}")
        ok, screenshot = await login(username, password, panel)

        now_bj = format_to_iso(now_beijing())
        status_icon = "✅" if ok else "❌"
        status_text = "登录成功" if ok else "登录失败"
        line = (
            f"🔹 *服务商*: `{('CT8' if 'ct8' in panel.lower() else 'Serv00')}`\n"
            f"👤 *账号*: `{username}`\n"
            f"🕒 *时间*: {now_bj}\n"
            f"{status_icon} *状态*: _{status_text}_\n"
        )
        if screenshot:
            line += f"🖼 截图: `{os.path.basename(screenshot)}`\n"
        line += "────────────────────\n"
        report.append(line)

        # 若失败且有截图，立即发送截图到 Telegram（并附短说明）
        if not ok and screenshot and os.path.exists(screenshot):
            caption = f"`{username}` 登录失败 — 请查看截图"
            send_telegram_photo(screenshot, caption=caption)

        # 随机延时，防止同时大量请求
        await delay_time(random.randint(1000, 6000))

    # 发送合并文本报告（可能会分多条发送）
    full_report = "\n".join(report) + "\n🏁 *所有账号操作已完成*"
    send_telegram_text(full_report)

    # 关闭浏览器
    await shutdown_browser()
    print("任务完成。")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手动中断，正在退出...")

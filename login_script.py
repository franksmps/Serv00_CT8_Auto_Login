import os
import json
import asyncio
import random
import requests
from datetime import datetime, timedelta, timezone
from pyppeteer import launch
import aiofiles

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def format_to_iso(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def now_utc():
    return datetime.now(timezone.utc)

def now_beijing():
    return now_utc() + timedelta(hours=8)

browser = None

async def delay_time(ms):
    await asyncio.sleep(ms / 1000)

async def login(username, password, panel, screenshot_dir='.'):
    global browser
    page = None
    serviceName = 'CT8' if 'ct8' in panel.lower() else 'Serv00'
    safe_user = username.replace('/', '_').replace('\\', '_')
    screenshot_path = os.path.join(screenshot_dir, f"screenshot_{serviceName}_{safe_user}.png")
    try:
        if not browser:
            browser = await launch(headless=True, args=[
                '--no-sandbox', '--disable-setuid-sandbox',
                '--disable-dev-shm-usage', '--disable-gpu'
            ])
        page = await browser.newPage()
        url = f'https://{panel}/login/?next=/'
        await page.goto(url, {"waitUntil": "networkidle2", "timeout": 30000})

        username_selectors = [
            'input[name="username"]', 'input[name="login"]', '#id_username', 'input[type="text"]'
        ]
        password_selectors = [
            'input[name="password"]', '#id_password', 'input[type="password"]'
        ]
        login_btn_selectors = [
            'button[type="submit"]', 'input[type="submit"]', 'button.login-button', 'button.btn'
        ]

        found_username = None
        found_password = None
        for sel in username_selectors:
            try:
                await page.waitForSelector(sel, {'visible': True, 'timeout': 7000})
                found_username = sel
                break
            except:
                continue
        for sel in password_selectors:
            try:
                await page.waitForSelector(sel, {'visible': True, 'timeout': 7000})
                found_password = sel
                break
            except:
                continue
        if not (found_username and found_password):
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
            raise Exception("找不到用户名或密码输入框")

        try:
            await page.click(found_username)
            await page.evaluate('(sel) => document.querySelector(sel).value = ""', found_username)
            await page.type(found_username, username, {'delay': 50})
        except:
            await page.evaluate('(sel, val) => { const el = document.querySelector(sel); if(el){ el.focus(); el.value = val; el.dispatchEvent(new Event("input", {bubbles:true})); }}', found_username, username)
        try:
            await page.click(found_password)
            await page.evaluate('(sel) => document.querySelector(sel).value = ""', found_password)
            await page.type(found_password, password, {'delay': 50})
        except:
            await page.evaluate('(sel, val) => { const el = document.querySelector(sel); if(el){ el.focus(); el.value = val; el.dispatchEvent(new Event("input", {bubbles:true})); }}', found_password, password)
        
        login_button = None
        for sel in login_btn_selectors:
            try:
                login_button = await page.waitForSelector(sel, {'visible': True, 'timeout': 6000})
                if login_button:
                    break
            except:
                continue

        if not login_button:
            login_texts = ["ZALOGUJ SIĘ", "Login", "Sign in", "登录"]
            for txt in login_texts:
                btns = await page.xpath(f'//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ", "abcdefghijklmnopqrstuvwxyząćęłńóśźż"), "{txt.lower()}")]')
                if btns:
                    login_button = btns[0]
                    break

        if not login_button:
            for txt in login_texts:
                btns = await page.xpath(f'//input[@type="submit" and contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ", "abcdefghijklmnopqrstuvwxyząćęłńóśźż"), "{txt.lower()}")]')
                if btns:
                    login_button = btns[0]
                    break

        if not login_button:
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
            raise Exception("找不到任何语言的登录按钮")

        try:
            await page.evaluate('(el) => el.scrollIntoView({behavior:"auto", block:"center"})', login_button)
        except:
            pass
        await asyncio.sleep(0.5)
        try:
            await login_button.click()
        except:
            await page.evaluate('(el) => el.click()', login_button)

        try:
            await page.waitForNavigation({"waitUntil": "networkidle2", "timeout": 12000})
        except:
            await asyncio.sleep(1)

        try:
            page_text = await page.evaluate('() => document.body.innerText')
        except:
            page_text = ""

        lowered = page_text.lower()
        if "captcha" in lowered or "verify" in lowered or "验证码" in lowered or "请验证" in lowered:
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
            raise Exception("有验证码或额外验证")
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
        if is_logged_in:
            if os.path.exists(screenshot_path):
                try: os.remove(screenshot_path)
                except: pass
            return True, ""
        else:
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
            return False, screenshot_path
    except Exception as e:
        print(f"{serviceName}账号 {username} 登录出错: {e}")
        try:
            if page: await page.screenshot({'path': screenshot_path, 'fullPage': True})
        except: pass
        return False, screenshot_path
    finally:
        if page:
            try: await page.close()
            except: pass

async def shutdown_browser():
    global browser
    if browser:
        try: await browser.close()
        except: pass
        browser = None

def send_telegram_text(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，跳过发送")
        return
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(',') if c.strip()]
    MAX_LEN = 3500
    parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    headers = {'Content-Type': 'application/json'}
    for part in parts:
        for chat in chat_ids:
            payload = {'chat_id': chat, 'text': part, 'parse_mode': 'Markdown'}
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code != 200:
                    print("发送 Telegram 文本失败:", resp.text)
            except Exception as e:
                print("发送 Telegram 文本异常:", e)

def send_telegram_photo(photo_path, caption=""):
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

async def main():
    try:
        async with aiofiles.open('accounts.json', mode='r', encoding='utf-8') as f:
            accounts_raw = await f.read()
        accounts = json.loads(accounts_raw)
    except Exception as e:
        print("读取 accounts.json 出错:", e)
        return

    report = []
    header = "📊 *Serv00/CT8 批量登录保活状态*\n━━━━━━━━━━━━━━"
    report.append(header)
    for account in accounts:
        username = account.get('username')
        password = account.get('password')
        panel = account.get('panel')
        if not (username and password and panel):
            print("信息不完整，跳过：", account)
            continue
        print(f"开始登录: {panel} / {username}")
        ok, screenshot = await login(username, password, panel)
        now_bj = format_to_iso(now_beijing())
        status_icon = "✅" if ok else "❌"
        status_text = "登录成功" if ok else "登录失败"
        line = (
            f"🔹服务商: `{('CT8' if 'ct8' in panel.lower() else 'Serv00')}`\n"
            f"👤账号: `{username}`\n"
            f"🕒时间: {now_bj}\n"
            f"{status_icon} 状态: _{status_text}_\n"
        )
        if screenshot:
            line += f"🖼截图: `{os.path.basename(screenshot)}`\n"
        line += "────────────────────\n"
        report.append(line)
        if not ok and screenshot and os.path.exists(screenshot):
            caption = f"`{username}` 登录失败，请查截图"
            send_telegram_photo(screenshot, caption=caption)
        await delay_time(random.randint(1000, 6000))
    full_report = "\n".join(report) + "\n🏁 *全部账号登录完成*"
    send_telegram_text(full_report)
    await shutdown_browser()
    print("任务完成。")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("中断，退出。")

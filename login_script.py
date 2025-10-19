import json
import asyncio
from pyppeteer import launch
from datetime import datetime, timedelta
import aiofiles
import random
import requests
import os

# 从环境变量中获取 Telegram Bot Token 和 Chat ID
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def format_to_iso(date):
    return date.strftime('%Y-%m-%d %H:%M:%S')

async def delay_time(ms):
    await asyncio.sleep(ms / 1000)

# 全局浏览器实例
browser = None

# telegram消息
message = ""

async def login(username, password, panel):
    """登录 Serv00 / CT8 面板"""
    global browser
    page = None
    serviceName = 'CT8' if 'ct8' in panel.lower() else 'Serv00'
    screenshot_path = f"screenshot_{serviceName}_{username}.png"

    try:
        if not browser:
            browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])

        page = await browser.newPage()
        url = f'https://{panel}/login/'
        await page.goto(url, {"waitUntil": "networkidle2"})

        # 可能的输入选择器
        username_selectors = ['input[name="username"]', '#id_username']
        password_selectors = ['input[name="password"]', '#id_password']
        login_button_selectors = ['button[type="submit"]', 'input[type="submit"]', '#submit']

        username_input = None
        password_input = None
        login_button = None

        # 自动匹配输入框
        for sel in username_selectors:
            username_input = await page.querySelector(sel)
            if username_input:
                break
        for sel in password_selectors:
            password_input = await page.querySelector(sel)
            if password_input:
                break
        for sel in login_button_selectors:
            login_button = await page.querySelector(sel)
            if login_button:
                break

        if not (username_input and password_input and login_button):
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
            raise Exception("登录页面结构已更改或找不到登录表单")

        # 输入账号密码
        await page.click(username_selectors[0])
        await page.keyboard.type(username)
        await page.click(password_selectors[0])
        await page.keyboard.type(password)

        # 点击登录
        await login_button.click()
        await page.waitForNavigation({"waitUntil": "networkidle2", "timeout": 10000})

        # 检查是否登录成功
        is_logged_in = await page.evaluate('''() => {
            return document.body.innerText.includes("Logout") ||
                   document.body.innerText.includes("登出") ||
                   document.querySelector('a[href="/logout/"]') !== null;
        }''')

        # 如果登录成功，访问面板页验证会话
        if is_logged_in:
            await page.goto(f'https://{panel}/panel/', {"waitUntil": "networkidle2"})
            panel_text = await page.content()
            if "Error" in panel_text or "Denied" in panel_text:
                is_logged_in = False

        # 成功后删除截图（如果存在旧截图）
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)

        return is_logged_in

    except Exception as e:
        print(f'{serviceName}账号 {username} 登录时出现错误: {e}')
        # 保存截图供排查
        if page:
            try:
                await page.screenshot({'path': screenshot_path, 'fullPage': True})
            except:
                pass
        return False

    finally:
        if page:
            await page.close()


async def shutdown_browser():
    global browser
    if browser:
        await browser.close()
        browser = None


async def main():
    global message

    try:
        async with aiofiles.open('accounts.json', mode='r', encoding='utf-8') as f:
            accounts_json = await f.read()
        accounts = json.loads(accounts_json)
    except Exception as e:
        print(f'读取 accounts.json 文件时出错: {e}')
        return

    message += "📊 *Serv00 & CT8 登录状态报告*\n\n"
    message += "━━━━━━━━━━━━━━━━━━━━\n"

    for account in accounts:
        username = account['username']
        password = account['password']
        panel = account['panel']
        serviceName = 'CT8' if 'ct8' in panel.lower() else 'Serv00'

        print(f"正在登录 {serviceName} - {username}")
        is_logged_in = await login(username, password, panel)

        now_beijing = format_to_iso(datetime.utcnow() + timedelta(hours=8))
        status_icon = "✅" if is_logged_in else "❌"
        status_text = "登录成功" if is_logged_in else "登录失败"
        screenshot_file = f"screenshot_{serviceName}_{username}.png"
        screenshot_info = f"🖼 截图: `{screenshot_file}`\n" if not is_logged_in else ""

        message += (
            f"🔹 *服务商*: `{serviceName}`\n"
            f"👤 *账号*: `{username}`\n"
            f"🕒 *时间*: {now_beijing}\n"
            f"{status_icon} *状态*: _{status_text}_\n"
            f"{screenshot_info}"
            "────────────────────\n"
        )

        delay = random.randint(1000, 8000)
        await delay_time(delay)

    message += "\n🏁 *所有账号操作已完成*"
    await send_telegram_message(message)
    print('所有账号登录完成！')
    await shutdown_browser()


async def send_telegram_message(message):
    formatted_message = f"""
📨 *Serv00 & CT8 保号脚本运行报告*
━━━━━━━━━━━━━━━━━━━━
🕘 北京时间: `{format_to_iso(datetime.utcnow() + timedelta(hours=8))}`
🌐 UTC时间: `{format_to_iso(datetime.utcnow())}`
━━━━━━━━━━━━━━━━━━━━

{message}
"""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': formatted_message,
        'parse_mode': 'Markdown',
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"发送消息到Telegram失败: {response.text}")
    except Exception as e:
        print(f"发送消息到Telegram时出错: {e}")


if __name__ == '__main__':
    asyncio.run(main())

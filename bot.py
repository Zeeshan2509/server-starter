import time
import re
import sys
import os
import base64
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError

# --- CONFIGURATION ---
GITHUB_TOKEN = os.environ.get('GH_PAT')
CENTRAL_REPO = os.environ.get('CENTRAL_REPO')
WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

# --- Selectors ---
USERNAME_SELECTOR = ".username"
PASSWORD_SELECTOR = ".password"
LOGIN_BUTTON_SELECTOR = ".login-button"
SERVER_SELECTOR = ".server-body"
START_BUTTON_SELECTOR = "button#start"
STOP_BUTTON_SELECTOR = "button#stop"
CONFIRM_BUTTON_SELECTOR = "button#confirm"
STATUS_LABEL_SELECTOR = "span.statuslabel-label"
QUEUE_TIME_SELECTOR = "div.server-status-label-left.queue-time"
LOG_URL = "https://aternos.org/log/"
LOG_CONTENT_SELECTOR = "div.page-content.page-log"

# --- Credentials ---
USERNAME = os.environ.get('ATERNOS_USER')
PASSWORD = os.environ.get('ATERNOS_PASS')

# Headers
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def sync_logs_to_storage():
    if not os.path.exists("Server Logs.txt"):
        return

    print("Starting upload sequence...")

    try:
        url = f"https://api.github.com/repos/{CENTRAL_REPO}/contents/Logs"
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 200:
            files = r.json()
            count = len([f for f in files if f['name'].startswith('Server Logs') and f['name'].endswith('.txt')])
            num = count + 1
        else:
            num = 1
    except Exception as e:
        print(f"⚠ Numbering error: {e}. Using timestamp failsafe.")
        num = datetime.now().strftime("%H%M")

    clean_name = f"Server Logs {num}"
    filename = f"{clean_name}.txt"
    file_path = "Server Logs.txt"

    try:
        with open(file_path, 'rb') as f:
            payload = {"content": f"**{clean_name}**"}
            files = {'file': (filename, f)}
            requests.post(WEBHOOK_URL, data=payload, files=files)
        print(f"✓ Uploaded to Discord: {filename}")
    except Exception as e:
        print(f"Discord error: {e}")

    try:
        url = f"https://api.github.com/repos/{CENTRAL_REPO}/contents/Logs/{filename}"
        with open(file_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")

        repo_orig = os.getenv('GITHUB_REPOSITORY', 'Bot').split('/')[-1]
        data = {"message": f"Add {filename} from {repo_orig}", "content": content}

        r = requests.put(url, json=data, headers=HEADERS)
        if r.status_code in [200, 201]:
            print(f"✓ Saved to central-storage: {filename}")
        else:
            print(f"❌ GitHub Storage failed: {r.text}")
    except Exception as e:
        print(f"GitHub Storage error: {e}")

def process_logs_filter():
    input_filename = 'Logs.txt'
    output_filename = 'Server Logs.txt'
    log_pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}):\d{2}.*?\]\s+Player\s+(connected|disconnected):\s+([^,]+)")

    symbols = {
        "Shayan1509": "◆",
        "Zeeshan0908": "✦",
        "Ahmadmirza238": "⬧",
        "Zeeshan3702": "✧"
    }

    sessions, total_seconds, output_content = {}, {}, []

    try:
        with open(input_filename, 'r', encoding="utf-8") as f:
            for line in f:
                if "Player connected: Bot" in line or "Player disconnected: Bot" in line: continue
                match = log_pattern.search(line)
                if match:
                    date_val, time_val, action, name = match.groups()
                    name = name.strip()
                    symbol = symbols.get(name, "•") # Default bullet if name is unknown

                    dt = datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M")
                    formatted_time = dt.strftime("%d/%m/%y %I:%M %p")
                    status = action.capitalize()

                    log_entry = f"{symbol} [{formatted_time}] {name} {status}\n\n"
                    
                    if not output_content or output_content[-1] != log_entry:
                        output_content.append(log_entry)

                    if action == "connected":
                        sessions[name] = dt
                    elif action == "disconnected" and name in sessions:
                        duration = dt - sessions[name]
                        total_seconds[name] = total_seconds.get(name, 0) + duration.total_seconds()
                        del sessions[name]

        if not output_content:
            print("No player activity found. Skipping file creation.")
            return

        final_file_data = []
        final_file_data.append("Total Connection Time\n\n")
        for player, seconds in total_seconds.items():
            h, m = int(seconds // 3600), int((seconds % 3600) // 60)
            
            h_label = "hour" if h == 1 else "hours"
            m_label = "minute" if m == 1 else "minutes"
            
            final_file_data.append(f"{player}: {h} {h_label} {m} {m_label}\n")

        final_file_data.append("\n---\n\n")
        final_file_data.extend(output_content)

        with open(output_filename, 'w', encoding="utf-8") as out_file:
            out_file.writelines(final_file_data)
        print("✓ Filtration Success: Results saved to 'Server Logs.txt'")

    except FileNotFoundError:
        print("Error: Could not find 'Logs.txt'")

def save_logs_action(page):
    print("Navigating to Logs...")
    page.goto(LOG_URL, wait_until="domcontentloaded", timeout=0)
    try:
        page.wait_for_selector(LOG_CONTENT_SELECTOR, timeout=0)
        log_text = page.locator(LOG_CONTENT_SELECTOR).inner_text()
        with open("Logs.txt", "w", encoding="utf-8") as f: f.write(log_text)
        process_logs_filter()
    except Exception as e:
        print(f"Failed to save logs: {e}")
    page.goto("https://aternos.org/server/", wait_until="domcontentloaded", timeout=0)

def handle_notifications(page):
    try:
        no_btn = page.get_by_role("button", name="No", exact=True)
        if no_btn.count() > 0 and no_btn.is_visible():
            no_btn.click()
            print("✓ Notification prompt handled.")
            return True
    except: pass
    return False

def get_server_status(page):
    try:
        return page.locator(STATUS_LABEL_SELECTOR).inner_text().strip().lower()
    except:
        return "unknown"

def wait_for_online(page, start_already_clicked=False, log_pending=False):
    print("Monitoring progress...")
    last_printed_state, queue_printed = "", False
    start_time = time.time()
    notif_handled, start_clicked = False, start_already_clicked

    while True:
        if not notif_handled:
            if handle_notifications(page): notif_handled = True

        status = get_server_status(page)

        if "offline" in status and not start_clicked:
            start_btn = page.locator(START_BUTTON_SELECTOR)
            if start_btn.is_visible() and start_btn.is_enabled():
                if not start_already_clicked:
                    save_logs_action(page)
                    log_pending = True
                    start_already_clicked = True
                start_btn.click()
                print("✓ Start button clicked.")
                start_clicked, start_time = True, time.time()

        if "offline" in status and start_clicked:
            if time.time() - start_time > 30:
                print("Stuck Offline for 30s. Refreshing...")
                page.reload(wait_until="domcontentloaded", timeout=0)
                page.wait_for_timeout(2000)
                notif_handled, start_clicked = False, False
                start_time = time.time()

        if "online" in status:
            print("🟢 Server is now Online.")
            if log_pending:
                sync_logs_to_storage()
            break

        if status != last_printed_state:
            if "preparing" in status: print("🟠 Status: Preparing...")
            elif "loading" in status: print("🟠 Status: Loading...")
            elif "starting" in status: print("🟢 Status: Starting...")
            elif "stopping" in status: print("🔴 Status: Stopping...")
            elif "saving" in status: print("🔴 Status: Saving...")
            last_printed_state = status

        if "queue" in status and not queue_printed:
            try:
                q_time = page.locator(QUEUE_TIME_SELECTOR).inner_text().strip()
                if q_time: print(f"🟡 Queue Remaining: {q_time}"); queue_printed = True
            except: pass

        confirm = page.locator(CONFIRM_BUTTON_SELECTOR)
        if confirm.is_visible() and confirm.is_enabled():
            confirm.click(force=True)
            print("✓ Confirm button clicked.")
            page.wait_for_timeout(5000)

        time.sleep(3)

def main():
    with sync_playwright() as p:
        print("Bot Started.")
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        fail_count = 0
        page = None

        while fail_count < 3:
            page = context.new_page()
            page.set_default_timeout(0)
            try:
                page.goto("https://aternos.org/go/", wait_until="domcontentloaded", timeout=60000)
                page.fill(USERNAME_SELECTOR, USERNAME); page.fill(PASSWORD_SELECTOR, PASSWORD)
                page.click(LOGIN_BUTTON_SELECTOR)
                page.wait_for_selector(SERVER_SELECTOR, state="visible", timeout=60000)
                page.click(SERVER_SELECTOR)
                page.wait_for_selector(STATUS_LABEL_SELECTOR, state="attached", timeout=30000)
                break
            except Exception as e:
                fail_count += 1
                page.close()
                print(f"Stuck at login. Resetting tab (Attempt {fail_count}/3)...")
                if fail_count >= 3:
                    print("Failed 3 times. Shutting down."); browser.close(); return

        try:
            page.wait_for_timeout(3000)
            handle_notifications(page)
            status = get_server_status(page)

            if "online" in status:
                print("🟢 Already Online. Closing bot.")
                return

            if "loading" in status or "starting" in status:
                print("Server Loading. Skipping logs...")
                wait_for_online(page, start_already_clicked=True, log_pending=False)
            elif any(x in status for x in ["stopping", "saving"]):
                print(f"Server is {status.upper()}. Waiting for 'Offline' to process logs...")
                wait_for_online(page, start_already_clicked=False, log_pending=False)
            else:
                save_logs_action(page)
                status = get_server_status(page)
                if "offline" in status:
                    print("🔴 Server Offline. Starting...")
                    page.locator(START_BUTTON_SELECTOR).click()
                    wait_for_online(page, start_already_clicked=True, log_pending=True)
                elif "queue" in status:
                    print("🟡 Server in Queue. Waiting for confirm...")
                    wait_for_online(page, start_already_clicked=True, log_pending=True)
                else:
                    wait_for_online(page, start_already_clicked=False, log_pending=True)

        except Exception as e:
            print(f"Critical Error: {e}")
        finally:
            print("Bot shutting down.")
            browser.close()

if __name__ == "__main__":
    main()

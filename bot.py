import time
import re
import sys
import os
import base64
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError

# --- CONFIGURATION (PULLED FROM GITHUB SECRETS) ---
GITHUB_TOKEN = os.environ.get('GH_PAT')
CENTRAL_REPO = os.environ.get('CENTRAL_REPO')
WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK')

# --- Selectors ---
USERNAME_SELECTOR = "input.username, input[autocomplete='username'], input[placeholder='Username'], input[name='user']"
PASSWORD_SELECTOR = "input.password, input[autocomplete='current-password'], input[type='password'], input[name='password']"
LOGIN_BUTTON_SELECTOR = ".login-button, button[type='submit'], #login"
SERVER_SELECTOR = ".servercard, .server-body"
START_BUTTON_SELECTOR = "button#start, #start, .server-start"
STOP_BUTTON_SELECTOR = "button#stop, #stop"
CONFIRM_BUTTON_SELECTOR = "button#confirm, #confirm, .btn-confirm"
STATUS_LABEL_SELECTOR = "span.statuslabel-label, .statuslabel-label"
QUEUE_TIME_SELECTOR = "div.server-status-label-left.queue-time, .queue-time"
LOG_URL = "https://aternos.org/log/"
LOG_CONTENT_SELECTOR = "div.page-content.page-log, .page-log, .log-body"

# --- Credentials (PULLED FROM GITHUB SECRETS) ---
USERNAME = os.environ.get('ATERNOS_USER')
PASSWORD = os.environ.get('ATERNOS_PASS')

# Headers
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def handle_adblock_and_vignettes(page):
    """Dismisses Google Vignettes (#google_vignette), CMP consent, and Aternos popups."""
    # 1. URL hash check
    try:
        if "google_vignette" in page.url:
            clean_url = page.url.split("#")[0]
            page.goto(clean_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # 2. Frame dismiss buttons
    try:
        for frame in page.frames:
            try:
                dismiss_btn = frame.locator("#dismiss-button, div[id='dismiss-button'], div[aria-label='Close ad']")
                if dismiss_btn.count() > 0 and dismiss_btn.first.is_visible():
                    dismiss_btn.first.click(force=True, timeout=2000)
                    page.wait_for_timeout(500)
            except Exception:
                pass
    except Exception:
        pass

    # 3. DOM popup dismiss buttons
    try:
        page.evaluate("""() => {
            const selectors = [
                'button:has-text("Continue")',
                '.btn-continue',
                '.adblock-continue',
                'button:has-text("Okay")',
                '.alert-okay',
                '.btn-okay',
                '.btn-primary:has-text("Continue")',
                '#dismiss-button',
                '.fc-button.fc-cta-consent'
            ];
            for (const sel of selectors) {
                try {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent !== null) {
                        el.click();
                    }
                } catch(e) {}
            }
        }""")
    except Exception:
        pass


def sync_logs_to_storage():
    """Numbers the log based on central repo count and uploads to Discord and GitHub."""
    if not os.path.exists("Server Logs.txt"):
        return

    log("Starting log upload sequence...")

    try:
        url = f"https://api.github.com/repos/{CENTRAL_REPO}/contents/Logs"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            files = r.json()
            count = len([f for f in files if f['name'].startswith('Server Logs') and f['name'].endswith('.txt')])
            num = count + 1
        else:
            num = 1
    except Exception as e:
        log(f"⚠ Numbering error: {e}. Using timestamp failsafe.")
        num = datetime.now().strftime("%H%M")

    clean_name = f"Server Logs {num}"
    filename = f"{clean_name}.txt"
    file_path = "Server Logs.txt"

    try:
        with open(file_path, 'rb') as f:
            payload = {"content": f"**{clean_name}**"}
            files = {'file': (filename, f)}
            requests.post(WEBHOOK_URL, data=payload, files=files, timeout=15)
        log(f"✓ Uploaded to Discord: {filename}")
    except Exception as e:
        log(f"Discord error: {e}")

    try:
        url = f"https://api.github.com/repos/{CENTRAL_REPO}/contents/Logs/{filename}"
        with open(file_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")

        data = {"message": f"Add {filename} Locally", "content": content}

        r = requests.put(url, json=data, headers=HEADERS, timeout=20)
        if r.status_code in [200, 201]:
            log(f"✓ Saved to central-storage: {filename}")
        else:
            log(f"❌ GitHub Storage failed: {r.text}")
    except Exception as e:
        log(f"GitHub Storage error: {e}")


def process_logs_filter():
    """Filters logs with unique symbols, duplicate check, and total time at the top."""
    input_filename = 'Logs.txt'
    output_filename = 'Server Logs.txt'
    log_pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}):\d{2}.*?\]\s+Player\s+(connected|disconnected):\s+([^,]+)")

    symbols = {
        "Shayan1509": "✷",
        "Zeeshan0908": "✦",
        "Ahmadmirza238": "⬧",
        "Zeeshan3702": "✧",
        "nightmare25505": "★"
    }

    sessions, total_seconds, output_content = {}, {}, []

    try:
        with open(input_filename, 'r', encoding="utf-8") as f:
            for line in f:
                if "Player connected: Bot" in line or "Player disconnected: Bot" in line:
                    continue
                match = log_pattern.search(line)
                if match:
                    date_val, time_val, action, name = match.groups()
                    name = name.strip()
                    symbol = symbols.get(name, "•")
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
            log("No player activity found. Skipping file creation.")
            return False

        final_file_data = ["Total Connection Time\n\n"]
        for player, seconds in total_seconds.items():
            h, m = int(seconds // 3600), int((seconds % 3600) // 60)
            h_label = "hour" if h == 1 else "hours"
            m_label = "minute" if m == 1 else "minutes"
            final_file_data.append(f"{player}: {h} {h_label} {m} {m_label}\n")
        final_file_data.append("\n---\n\n")
        final_file_data.extend(output_content)

        with open(output_filename, 'w', encoding="utf-8") as out_file:
            out_file.writelines(final_file_data)
        log("✓ Filtration Success: Results saved to 'Server Logs.txt'")
        return True
    except FileNotFoundError:
        log("Error: Could not find 'Logs.txt'")
        return False


def save_logs_action(page):
    """Saves prior session logs with a strict timeout so it never hangs server startup."""
    log("Navigating to Logs to archive prior session...")
    fresh_log_url = f"{LOG_URL}?t={int(time.time())}"
    try:
        page.goto(fresh_log_url, wait_until="domcontentloaded", timeout=15000)
        handle_adblock_and_vignettes(page)
        page.wait_for_timeout(2000)
        page.wait_for_selector(LOG_CONTENT_SELECTOR, timeout=10000)
        log_text = page.locator(LOG_CONTENT_SELECTOR).first.inner_text()
        with open("Logs.txt", "w", encoding="utf-8") as f:
            f.write(log_text)
        return process_logs_filter()
    except Exception as e:
        log(f"Notice: Could not archive prior logs ({e}). Proceeding with server start.")
        return False
    finally:
        try:
            page.goto("https://aternos.org/server/", wait_until="domcontentloaded", timeout=20000)
            handle_adblock_and_vignettes(page)
        except Exception:
            pass


def handle_notifications(page):
    """Priority-based notification and EULA handler."""
    try:
        # Priority 1: EULA Acceptance
        eula_btn = page.get_by_role("button", name="Yes, I accept the EULA.", exact=False)
        if eula_btn.count() > 0 and eula_btn.first.is_visible():
            eula_btn.first.click()
            log("✓ EULA accepted.")
            return True

        # Priority 2: Generic 'No' Button
        no_btn = page.get_by_role("button", name="No", exact=True)
        if no_btn.count() > 0 and no_btn.first.is_visible():
            no_btn.first.click()
            log("✓ Notification prompt handled.")
            return True
    except Exception:
        pass
    return False


def get_server_status(page):
    try:
        return page.locator(STATUS_LABEL_SELECTOR).first.inner_text().strip().lower()
    except Exception:
        return "unknown"


def wait_for_online(page, start_already_clicked=False, log_pending=False):
    log("Monitoring progress...")
    last_printed_state = ""
    queue_printed = False
    overall_start_time = time.time()
    start_time = time.time()
    notif_handled = False
    start_clicked = start_already_clicked
    logs_attempted = log_pending

    # Max 20 minutes wait
    MAX_WAIT_SECONDS = 20 * 60

    while time.time() - overall_start_time < MAX_WAIT_SECONDS:
        handle_adblock_and_vignettes(page)
        if not notif_handled:
            if handle_notifications(page):
                notif_handled = True

        status = get_server_status(page)

        # Offline state - Click Start!
        if "offline" in status and not start_clicked:
            start_btn = page.locator(START_BUTTON_SELECTOR).first
            if start_btn.count() > 0 and start_btn.is_visible() and start_btn.is_enabled():
                if not logs_attempted:
                    logs_attempted = True
                    log_pending = save_logs_action(page)
                    # Re-verify start button after returning from logs
                    start_btn = page.locator(START_BUTTON_SELECTOR).first

                log("Clicking Start button...")
                handle_adblock_and_vignettes(page)
                start_btn.click(force=True)
                log("✓ Start button clicked.")
                start_clicked = True
                start_time = time.time()
                time.sleep(5)
                continue

        # If stuck in offline after clicking start for > 35s, refresh
        if "offline" in status and start_clicked:
            elapsed = time.time() - start_time
            if elapsed > 35:
                log(f"Stuck Offline for {int(elapsed)}s after clicking start. Refreshing...")
                page.reload(wait_until="domcontentloaded", timeout=20000)
                handle_adblock_and_vignettes(page)
                page.wait_for_timeout(3000)
                notif_handled = False
                start_clicked = False
                start_time = time.time()

        if "online" in status:
            log("🟢 Server is now Online!")
            if log_pending:
                sync_logs_to_storage()
            return True

        if status != last_printed_state and status != "unknown":
            if "preparing" in status: log("🟠 Status: Preparing...")
            elif "loading" in status: log("🟠 Status: Loading...")
            elif "starting" in status: log("🟢 Status: Starting...")
            elif "stopping" in status: log("🔴 Status: Stopping...")
            elif "saving" in status: log("🔴 Status: Saving...")
            else: log(f"Server status: {status}")
            last_printed_state = status

        if "queue" in status:
            start_time = time.time()
            if not queue_printed:
                try:
                    q_time = page.locator(QUEUE_TIME_SELECTOR).first.inner_text().strip()
                    if q_time:
                        log(f"🟡 Queue Remaining: {q_time}")
                        queue_printed = True
                except Exception:
                    pass

        # Confirm queue popup if present
        confirm = page.locator(CONFIRM_BUTTON_SELECTOR).first
        if confirm.count() > 0 and confirm.is_visible() and confirm.is_enabled():
            confirm.click(force=True)
            log("✓ Confirm button clicked.")
            try:
                confirm.wait_for(state="hidden", timeout=10000)
            except Exception:
                pass

        time.sleep(4)

    log("Timeout waiting for server to reach online state.")
    return False


def login_and_select_server(page):
    log("Navigating to Aternos...")
    page.goto("https://aternos.org/go/", wait_until="domcontentloaded", timeout=45000)
    handle_adblock_and_vignettes(page)

    # 1. Already on server page?
    if "/server" in page.url and "/servers" not in page.url:
        log("Already on server dashboard.")
        return True

    # 2. Check if we need to log in
    if "/servers" not in page.url and "/server" not in page.url:
        if not USERNAME or not PASSWORD:
            raise ValueError("Missing ATERNOS_USER or ATERNOS_PASS environment variables.")
        
        log("Filling login credentials...")
        user_input = page.locator(USERNAME_SELECTOR).first
        user_input.wait_for(state="visible", timeout=20000)
        user_input.fill(USERNAME)
        
        pass_input = page.locator(PASSWORD_SELECTOR).first
        pass_input.wait_for(state="visible", timeout=10000)
        pass_input.fill(PASSWORD)
        
        login_btn = page.locator(LOGIN_BUTTON_SELECTOR).first
        login_btn.wait_for(state="visible", timeout=10000)
        login_btn.click()
        handle_adblock_and_vignettes(page)
        page.wait_for_timeout(3000)

    # 3. Select Server
    if "/server" not in page.url or "/servers" in page.url:
        log("Selecting server card...")
        handle_adblock_and_vignettes(page)
        try:
            card = page.locator(SERVER_SELECTOR).first
            card.wait_for(state="visible", timeout=15000)
            card.click(force=True)
        except Exception as e:
            log(f"Server card click note: {e}. Trying direct navigation to /server/...")
            page.goto("https://aternos.org/server/", wait_until="domcontentloaded", timeout=30000)

    handle_adblock_and_vignettes(page)
    page.wait_for_selector(STATUS_LABEL_SELECTOR, state="attached", timeout=25000)
    log(f"Successfully arrived on server dashboard: {page.url}")
    return True


def main():
    log("Bot Started.")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )

        fail_count = 0
        while fail_count < 3:
            page = context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(45000)
            try:
                login_and_select_server(page)
                break
            except Exception as e:
                fail_count += 1
                try:
                    os.makedirs("./artifacts", exist_ok=True)
                    page.screenshot(path=f"./artifacts/login_fail_attempt_{fail_count}.png")
                except Exception:
                    pass
                log(f"Stuck at login/select. Attempt {fail_count}/3. Error: {e}")
                page.close()
                if fail_count >= 3:
                    log("Failed 3 times. Shutting down.")
                    browser.close()
                    sys.exit(1)

        try:
            page.wait_for_timeout(2000)
            handle_notifications(page)
            status = get_server_status(page)

            if "online" in status:
                log("🟢 Already Online. Closing bot.")
                return

            if "loading" in status or "starting" in status:
                log("Server is Loading/Starting. Skipping logs...")
                wait_for_online(page, start_already_clicked=True, log_pending=False)
            elif any(x in status for x in ["stopping", "saving"]):
                log(f"Server is {status.upper()}. Waiting for 'Offline' to process logs...")
                wait_for_online(page, start_already_clicked=False, log_pending=False)
            else:
                wait_for_online(page, start_already_clicked=False, log_pending=False)

        except Exception as e:
            log(f"Critical Error: {e}")
        finally:
            log("Bot shutting down.")
            browser.close()


if __name__ == "__main__":
    main()

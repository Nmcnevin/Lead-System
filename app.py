"""
Lead Generation System - Render Optimized
Fixed for cloud deployment with better detection bypass
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import time
import re
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
import os
import warnings
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Lead Generation System", page_icon="🎯", layout="wide", initial_sidebar_state="collapsed")

for key, val in [('extracted_data', None), ('is_scraping', False), ('error_log', []), ('extraction_stats', {})]:
    if key not in st.session_state:
        st.session_state[key] = val

def log_error(t, m, d=None):
    st.session_state.error_log.append({'time': datetime.now().strftime("%H:%M:%S"), 'type': t, 'msg': m, 'detail': d})
    logger.error(f"{t}: {m} - {d}")

def display_errors():
    if st.session_state.error_log:
        with st.expander(f"⚠️ Errors ({len(st.session_state.error_log)})", expanded=False):
            for e in st.session_state.error_log[-15:]:
                st.text(f"[{e['time']}] {e['type']}: {e['msg']}")

def get_driver():
    """Optimized Chrome driver for Render deployment"""
    opts = Options()
    
    # Core headless settings
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    
    # Memory optimization for free tier
    opts.add_argument("--single-process")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-plugins")
    
    # Anti-detection
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument("--start-maximized")
    
    # Realistic user agent
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    # Language and locale
    opts.add_argument("--lang=en-US,en")
    opts.add_argument("--accept-lang=en-US,en;q=0.9")
    
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option('useAutomationExtension', False)
    
    # Additional prefs
    opts.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.geolocation": 2,
    })
    
    try:
        if os.path.exists("/usr/bin/chromedriver"):
            svc = Service("/usr/bin/chromedriver")
        else:
            svc = Service()
        
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(3)
        
        # Execute CDP commands to mask automation
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        })
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        logger.info("✅ Driver ready")
        return driver
    except Exception as e:
        logger.error(f"❌ Driver failed: {e}")
        return None

def safe_get_text(driver, xpath):
    try:
        el = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, xpath)))
        return el.text.strip() if el.text else "N/A"
    except:
        return "N/A"

def safe_get_attr(driver, xpath, attr):
    try:
        el = driver.find_element(By.XPATH, xpath)
        return el.get_attribute(attr) or "N/A"
    except:
        return "N/A"

def get_phone(driver):
    xpaths = [
        "//button[@data-item-id='phone:tel']",
        "//button[contains(@aria-label,'Phone')]",
        "//a[starts-with(@href,'tel:')]"
    ]
    for xp in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xp)
            for el in els:
                aria = el.get_attribute('aria-label') or ""
                href = el.get_attribute('href') or ""
                txt = el.text or ""
                for s in [aria, href.replace('tel:', ''), txt]:
                    m = re.search(r'[\+\d][\d\s\-\(\)]{7,}', s)
                    if m:
                        return m.group().strip()
        except:
            continue
    return "N/A"

def get_address(driver):
    xpaths = [
        "//button[@data-item-id='address']",
        "//button[contains(@aria-label,'Address')]",
        "//div[contains(@class,'rogA2c')]"
    ]
    for xp in xpaths:
        try:
            el = driver.find_element(By.XPATH, xp)
            aria = el.get_attribute('aria-label')
            if aria:
                return aria.split(':')[-1].strip() if ':' in aria else aria.strip()
            if el.text:
                return el.text.strip()
        except:
            continue
    return "N/A"

def get_website(driver):
    xpaths = [
        "//a[@data-item-id='authority']",
        "//a[contains(@aria-label,'Website')]",
        "//a[contains(@href,'http') and not(contains(@href,'google'))]"
    ]
    for xp in xpaths:
        try:
            el = driver.find_element(By.XPATH, xp)
            href = el.get_attribute('href')
            if href and 'google' not in href:
                return href
        except:
            continue
    return "N/A"

def get_rating(driver):
    try:
        el = driver.find_element(By.XPATH, "//div[@class='F7nice']//span[@aria-hidden='true']")
        return el.text.strip() if el.text else "N/A"
    except:
        return "N/A"

def extract_emails(text):
    if not text:
        return []
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(pattern, text)
    bad = ['example', 'test', 'sentry', 'wix', 'domain.com']
    return list(set([e for e in emails if not any(b in e.lower() for b in bad)]))[:3]

def scrape_website(url, timeout=5):
    result = {'emails': [], 'social': {}}
    if not url or url == 'N/A':
        return result
    try:
        if not url.startswith('http'):
            url = 'https://' + url
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=timeout, verify=False)
        soup = BeautifulSoup(r.text, 'html.parser')
        result['emails'] = extract_emails(soup.get_text())
        
        # Social media
        social = {'facebook': 'facebook.com', 'instagram': 'instagram.com', 'twitter': 'twitter.com', 'linkedin': 'linkedin.com'}
        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            for name, domain in social.items():
                if domain in href and name not in result['social']:
                    result['social'][name] = link['href']
    except:
        pass
    return result

def scroll_panel(driver, panel, max_scroll=12, callback=None):
    """Scroll results panel to load more businesses"""
    last_h = 0
    same = 0
    for i in range(max_scroll):
        try:
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", panel)
            time.sleep(2.5)
            h = driver.execute_script("return arguments[0].scrollHeight", panel)
            
            # Count businesses found
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/']")
            if callback:
                callback(f"📜 Scroll {i+1}: Found {len(links)} businesses")
            
            if h == last_h:
                same += 1
                if same >= 2:
                    break
            else:
                same = 0
                last_h = h
        except:
            break
    time.sleep(1.5)

def extract_business_details(driver, url, keyword):
    """Extract all details from a business page"""
    business = {
        'Business Name': 'N/A',
        'Email ID': 'N/A',
        'Phone Number': 'N/A',
        'Location/Address': 'N/A',
        'Business Category': keyword,
        'Website URL': 'N/A',
        'Social Media': 'N/A',
        'Rating': 'N/A'
    }
    
    try:
        driver.get(url)
        time.sleep(random.uniform(2.5, 4))
        
        # Wait for name to load
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.DUwDvf, h1.fontHeadlineLarge"))
        )
        
        # Get name
        for sel in ["h1.DUwDvf", "h1.fontHeadlineLarge", "div[role='main'] h1"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.text:
                    business['Business Name'] = el.text.strip()
                    break
            except:
                continue
        
        if business['Business Name'] == 'N/A':
            return None
        
        business['Phone Number'] = get_phone(driver)
        business['Location/Address'] = get_address(driver)
        business['Website URL'] = get_website(driver)
        business['Rating'] = get_rating(driver)
        
        logger.info(f"✅ Extracted: {business['Business Name']}")
        return business
        
    except Exception as e:
        logger.error(f"❌ Extract failed: {e}")
        return None

def scrape_leads(keyword, location=None, max_results=10, get_contact=True, callback=None):
    """Main scraping function"""
    results = []
    driver = None
    stats = {'found': 0, 'extracted': 0, 'emails': 0, 'errors': 0}
    st.session_state.error_log = []
    
    try:
        if callback:
            callback("🚀 Starting Chrome...")
        
        driver = get_driver()
        if not driver:
            return pd.DataFrame(), "❌ Chrome failed to start", stats
        
        # Build search URL
        if location:
            query = f"{keyword} in {location}".replace(' ', '+')
        else:
            query = keyword.replace(' ', '+')
        
        url = f"https://www.google.com/maps/search/{query}"
        
        if callback:
            callback(f"🌐 Loading Google Maps...")
        
        try:
            driver.get(url)
            time.sleep(random.uniform(4, 6))
        except Exception as e:
            return pd.DataFrame(), f"❌ Failed to load Maps: {e}", stats
        
        # Accept cookies if present
        try:
            btns = driver.find_elements(By.XPATH, "//button[contains(text(),'Accept')]")
            if btns:
                btns[0].click()
                time.sleep(1)
        except:
            pass
        
        # Find results panel
        if callback:
            callback("🔍 Finding results...")
        
        panel = None
        for sel in ["div[role='feed']", "div.m6QErb.DxyBCb"]:
            try:
                panel = WebDriverWait(driver, 12).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                if panel:
                    logger.info(f"✅ Found panel: {sel}")
                    break
            except:
                continue
        
        if not panel:
            return pd.DataFrame(), "❌ No results panel found", stats
        
        # Scroll to load results
        if callback:
            callback("📜 Loading more results...")
        
        scroll_panel(driver, panel, max_scroll=12, callback=callback)
        
        # Collect business URLs
        if callback:
            callback("📋 Collecting business links...")
        
        links = set()
        for sel in ["a[href*='/maps/place/']", "a.hfpxzc"]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    href = el.get_attribute('href')
                    if href and '/maps/place/' in href:
                        links.add(href)
            except:
                continue
        
        links = list(links)[:max_results]
        stats['found'] = len(links)
        
        if not links:
            return pd.DataFrame(), "❌ No businesses found", stats
        
        if callback:
            callback(f"✅ Found {len(links)} businesses")
        
        # Extract each business
        for i, link in enumerate(links):
            if callback:
                callback(f"📍 Extracting {i+1}/{len(links)}...")
            
            biz = extract_business_details(driver, link, keyword)
            if biz:
                results.append(biz)
                stats['extracted'] += 1
            else:
                stats['errors'] += 1
            
            time.sleep(random.uniform(1, 2))
        
        # Get contact info from websites
        if get_contact and results:
            if callback:
                callback("🌐 Scraping websites for emails...")
            
            for i, biz in enumerate(results):
                web = biz.get('Website URL', 'N/A')
                if web and web != 'N/A':
                    if callback:
                        callback(f"🔍 Website {i+1}/{len(results)}: {biz['Business Name'][:25]}")
                    
                    info = scrape_website(web)
                    if info['emails']:
                        biz['Email ID'] = ', '.join(info['emails'])
                        stats['emails'] += 1
                    if info['social']:
                        biz['Social Media'] = ' | '.join([f"{k}: {v}" for k,v in info['social'].items()])
                    
                    time.sleep(random.uniform(0.5, 1.5))
        
        st.session_state.extraction_stats = stats
        
        if results:
            return pd.DataFrame(results), None, stats
        return pd.DataFrame(), "❌ No data extracted", stats
        
    except Exception as e:
        log_error("CRITICAL", str(e))
        return pd.DataFrame(), f"❌ Error: {e}", stats
    
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("✅ Driver closed")
            except:
                pass

# ============================================
# STREAMLIT UI
# ============================================

st.title("🎯 Lead Generation System")
st.caption("Extract business leads from Google Maps")

display_errors()
st.divider()

# Mode Selection
st.subheader("🔄 Extraction Mode")
mode = st.radio(
    "Select mode:",
    ["🎯 Target Based (Keyword + Location)", "🔍 Keyword Search (Global)"],
    horizontal=True
)

is_target = "Target" in mode

if is_target:
    st.info("Search businesses by keyword in a specific location")
else:
    st.info("Search businesses globally by keyword only")

st.divider()

# Input Fields
st.subheader("🔍 Search Parameters")

if is_target:
    c1, c2 = st.columns(2)
    with c1:
        keyword = st.text_input("Keyword", placeholder="e.g., Coffee Shop, Gym, Restaurant")
    with c2:
        location = st.text_input("Location", placeholder="e.g., Mumbai, New York, London")
else:
    keyword = st.text_input("Keyword", placeholder="e.g., Tesla Dealership, Apple Store")
    location = None

num = st.slider("Number of Results", 3, 15, 8)
get_email = st.checkbox("Extract Emails & Social Media", value=True)

st.divider()

# Start Button
st.subheader("🚀 Extract Leads")

c1, c2, c3 = st.columns([1,1,1])
with c2:
    go = st.button("🚀 START EXTRACTION", type="primary", use_container_width=True, disabled=st.session_state.is_scraping)

if go:
    # Validation
    if is_target and (not keyword or not location):
        st.error("❌ Enter both keyword and location")
        st.stop()
    elif not is_target and not keyword:
        st.error("❌ Enter a keyword")
        st.stop()
    
    st.session_state.is_scraping = True
    st.session_state.error_log = []
    
    prog = st.progress(0)
    status = st.empty()
    
    def update(msg):
        status.info(msg)
        prog.progress(min(95, random.randint(10, 90)))
    
    t0 = time.time()
    
    df, err, stats = scrape_leads(
        keyword=keyword,
        location=location if is_target else None,
        max_results=num,
        get_contact=get_email,
        callback=update
    )
    
    elapsed = time.time() - t0
    prog.progress(100)
    
    if err:
        st.error(err)
        status.warning(f"Failed after {elapsed:.1f}s")
    elif not df.empty:
        st.session_state.extracted_data = df
        status.empty()
        prog.empty()
        st.success(f"✅ Extracted **{len(df)} leads** in {elapsed:.1f}s!")
        
        # Stats
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Found", stats['found'])
        c2.metric("Extracted", stats['extracted'])
        c3.metric("Emails", stats['emails'])
        c4.metric("Errors", stats['errors'])
        
        st.balloons()
    else:
        st.warning("⚠️ No results. Try different keywords.")
    
    display_errors()
    st.session_state.is_scraping = False
    st.rerun()

st.divider()

# Results
st.subheader("📊 Results")

if st.session_state.extracted_data is not None:
    df = st.session_state.extracted_data
    
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("📍 Total", len(df))
    c2.metric("📧 Emails", len(df[df['Email ID'] != 'N/A']))
    c3.metric("📞 Phones", len(df[df['Phone Number'] != 'N/A']))
    c4.metric("🌐 Websites", len(df[df['Website URL'] != 'N/A']))
    
    st.dataframe(df, use_container_width=True, height=400)
else:
    st.info("👆 Enter parameters and click START to extract leads")

st.divider()

# Download
st.subheader("💾 Download")

if st.session_state.extracted_data is not None:
    df = st.session_state.extracted_data
    fname = f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    csv = df.to_csv(index=False, encoding='utf-8-sig')
    
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        st.download_button("📥 DOWNLOAD CSV", csv, fname, "text/csv", use_container_width=True, type="primary")
    
    st.success(f"✅ {len(df)} leads ready for download")
else:
    st.button("📥 Download CSV", disabled=True)

st.divider()
st.caption("🚀 Lead Generation v4.0 | Optimized for Cloud Deployment")
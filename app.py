"""
Lead Generation System - Production Ready
Optimized for Streamlit Cloud & Render Deployment
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
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    StaleElementReferenceException, 
    WebDriverException
)
import time
import re
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page Configuration
st.set_page_config(
    page_title="Lead Generation System",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize session state
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'is_scraping' not in st.session_state:
    st.session_state.is_scraping = False
if 'error_log' not in st.session_state:
    st.session_state.error_log = []
if 'extraction_stats' not in st.session_state:
    st.session_state.extraction_stats = {}

# ============================================
# ERROR LOGGING
# ============================================

def log_error(error_type, message, details=None):
    """Centralized error logging"""
    error_entry = {
        'timestamp': datetime.now().strftime("%H:%M:%S"),
        'type': error_type,
        'message': message,
        'details': details
    }
    st.session_state.error_log.append(error_entry)
    logger.error(f"{error_type}: {message} - {details}")
    return error_entry

def display_error_log():
    """Display error log in UI"""
    if st.session_state.error_log:
        with st.expander(f"⚠️ Error Log ({len(st.session_state.error_log)} issues)", expanded=False):
            for error in st.session_state.error_log[-20:]:
                st.text(f"[{error['timestamp']}] {error['type']}: {error['message']}")
                if error['details']:
                    st.caption(f"   Details: {error['details']}")

# ============================================
# WEBDRIVER INITIALIZATION (NO CACHING - FIXES SESSION ERROR)
# ============================================

def get_chrome_driver():
    """
    Initialize Chrome driver - creates FRESH instance each time
    This prevents 'invalid session id' errors
    """
    options = Options()
    
    # Essential options for deployment
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920x1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--single-process")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    
    # User agent
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    try:
        # Detect environment and use appropriate path
        if os.path.exists("/usr/bin/chromedriver"):
            # Streamlit Cloud or Chromium installation
            service = Service(executable_path="/usr/bin/chromedriver")
            logger.info("Using chromedriver from /usr/bin/")
        elif os.path.exists("/usr/local/bin/chromedriver"):
            # Render/Docker with Chrome
            service = Service(executable_path="/usr/local/bin/chromedriver")
            logger.info("Using chromedriver from /usr/local/bin/")
        else:
            # Fallback to system PATH
            service = Service()
            logger.info("Using chromedriver from system PATH")
        
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(10)
        logger.info("✅ Chrome driver initialized successfully")
        return driver
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Chrome driver: {str(e)}")
        return None

# ============================================
# EMAIL & SOCIAL MEDIA EXTRACTION
# ============================================

def extract_emails_from_text(text):
    """Extract email addresses from text"""
    try:
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        
        fake_patterns = [
            'example.com', 'domain.com', 'test.com', 'sample.com', 
            'yoursite.com', 'yourdomain.com', 'email.com', 'mail.com', 
            'image', 'sentry', 'wixpress', 'placeholder', 'dummy', 'fake'
        ]
        
        valid_emails = []
        for email in emails:
            email_lower = email.lower()
            if not any(fake in email_lower for fake in fake_patterns):
                if email not in valid_emails and len(email) < 100:
                    valid_emails.append(email)
        
        return valid_emails
    except Exception as e:
        log_error("EMAIL_EXTRACTION", "Failed to extract emails", str(e))
        return []

def extract_social_media_links(soup, base_url):
    """Extract social media profile links"""
    social_platforms = {
        'facebook': ['facebook.com', 'fb.com'],
        'instagram': ['instagram.com'],
        'twitter': ['twitter.com', 'x.com'],
        'linkedin': ['linkedin.com'],
        'youtube': ['youtube.com'],
    }
    
    found_social = {}
    
    try:
        links = soup.find_all('a', href=True)
        
        for link in links:
            try:
                href = link.get('href', '')
                
                if href.startswith('/'):
                    href = urljoin(base_url, href)
                
                for platform, domains in social_platforms.items():
                    if platform not in found_social:
                        for domain in domains:
                            if domain in href.lower():
                                if '?' in href:
                                    href = href.split('?')[0]
                                found_social[platform] = href
                                break
            except:
                continue
        
        return found_social
    except Exception as e:
        log_error("SOCIAL_EXTRACTION", "Failed to extract social media", str(e))
        return found_social

def scrape_website_for_contact_info(website_url, business_name="Unknown", timeout=8):
    """Scrape website for email and social media"""
    result = {
        'emails': [],
        'social_media': {},
        'error': None
    }
    
    if not website_url or website_url == 'N/A':
        result['error'] = "No website URL"
        return result
    
    try:
        if not website_url.startswith(('http://', 'https://')):
            website_url = 'https://' + website_url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(
            website_url, 
            headers=headers, 
            timeout=timeout, 
            allow_redirects=True, 
            verify=False
        )
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '')
        if 'text/html' not in content_type.lower():
            result['error'] = f"Non-HTML: {content_type}"
            return result
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        
        if not page_text or len(page_text) < 100:
            result['error'] = "Empty content"
            return result
        
        # Extract emails
        emails = extract_emails_from_text(page_text)
        
        # Check mailto links
        mailto_links = soup.find_all('a', href=re.compile(r'^mailto:', re.I))
        for link in mailto_links:
            try:
                email = link.get('href', '').replace('mailto:', '').split('?')[0].strip()
                if email and email not in emails and '@' in email:
                    emails.append(email)
            except:
                continue
        
        result['emails'] = emails[:3]
        result['social_media'] = extract_social_media_links(soup, website_url)
        
        # Try contact page if no email found
        if not result['emails']:
            contact_urls = []
            for link in soup.find_all('a', href=True):
                try:
                    href = link.get('href', '').lower()
                    text = link.get_text().lower()
                    
                    if any(word in href or word in text for word in ['contact', 'about']):
                        full_url = urljoin(website_url, link.get('href'))
                        if full_url not in contact_urls and len(contact_urls) < 2:
                            contact_urls.append(full_url)
                except:
                    continue
            
            if contact_urls:
                try:
                    contact_response = requests.get(
                        contact_urls[0], 
                        headers=headers, 
                        timeout=5, 
                        verify=False
                    )
                    contact_soup = BeautifulSoup(contact_response.text, 'html.parser')
                    contact_emails = extract_emails_from_text(contact_soup.get_text())
                    
                    mailto_links = contact_soup.find_all('a', href=re.compile(r'^mailto:', re.I))
                    for link in mailto_links:
                        try:
                            email = link.get('href', '').replace('mailto:', '').split('?')[0].strip()
                            if email and email not in contact_emails:
                                contact_emails.append(email)
                        except:
                            continue
                    
                    result['emails'] = contact_emails[:3]
                except:
                    pass
        
        if not result['emails'] and not result['social_media']:
            result['error'] = "No contact info found"
        
        return result
        
    except requests.Timeout:
        result['error'] = f"Timeout ({timeout}s)"
        return result
    except requests.ConnectionError:
        result['error'] = "Connection failed"
        return result
    except requests.HTTPError as e:
        result['error'] = f"HTTP {e.response.status_code}"
        return result
    except Exception as e:
        result['error'] = f"Error: {str(e)[:30]}"
        return result

# ============================================
# UTILITY FUNCTIONS
# ============================================

def extract_text_safe(driver, xpath, attribute=None):
    """Safely extract text from element"""
    try:
        element = driver.find_element(By.XPATH, xpath)
        if attribute:
            value = element.get_attribute(attribute)
            return value if value else "N/A"
        text = element.text
        return text if text else "N/A"
    except:
        return "N/A"

def extract_phone_number(driver, business_name="Unknown"):
    """Extract phone number"""
    phone_xpaths = [
        "//button[contains(@data-item-id, 'phone')]",
        "//button[contains(@aria-label, 'Phone')]",
        "//a[starts-with(@href, 'tel:')]",
        "//div[contains(@class, 'AeaXub')]//button[contains(@class, 'CsEnBe')]"
    ]
    
    for xpath in phone_xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for element in elements:
                aria_label = element.get_attribute('aria-label')
                if aria_label:
                    phone_match = re.search(r'[\+\d][\d\s\-\(\)\.]{7,}', aria_label)
                    if phone_match:
                        return phone_match.group().strip()
                
                href = element.get_attribute('href')
                if href and href.startswith('tel:'):
                    return href.replace('tel:', '').strip()
                
                text = element.text
                if text:
                    phone_match = re.search(r'[\+\d][\d\s\-\(\)\.]{7,}', text)
                    if phone_match:
                        return phone_match.group().strip()
        except:
            continue
    
    return "N/A"

def extract_address(driver, business_name="Unknown"):
    """Extract address"""
    address_xpaths = [
        "//button[contains(@data-item-id, 'address')]",
        "//button[contains(@aria-label, 'Address')]",
        "//div[contains(@class, 'Io6YTe')]"
    ]
    
    for xpath in address_xpaths:
        try:
            element = driver.find_element(By.XPATH, xpath)
            aria_label = element.get_attribute('aria-label')
            if aria_label:
                if ':' in aria_label:
                    return aria_label.split(':', 1)[1].strip()
                return aria_label.strip()
            
            text = element.text
            if text:
                return text.strip()
        except:
            continue
    
    return "N/A"

def extract_website(driver, business_name="Unknown"):
    """Extract website"""
    website_xpaths = [
        "//a[contains(@data-item-id, 'authority')]",
        "//a[contains(@aria-label, 'Website')]",
        "//a[contains(@class, 'CsEnBe') and contains(@href, 'http')]"
    ]
    
    for xpath in website_xpaths:
        try:
            element = driver.find_element(By.XPATH, xpath)
            href = element.get_attribute('href')
            if href and 'google.com' not in href:
                return href
        except:
            continue
    
    return "N/A"

def scroll_results_panel(driver, panel, max_scrolls=8):
    """Scroll to load all results"""
    scroll_count = 0
    last_height = driver.execute_script("return arguments[0].scrollHeight", panel)
    no_change_count = 0
    
    while scroll_count < max_scrolls:
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", panel)
            time.sleep(random.uniform(1.5, 2.5))
            
            new_height = driver.execute_script("return arguments[0].scrollHeight", panel)
            
            if new_height == last_height:
                no_change_count += 1
                if no_change_count >= 3:
                    break
            else:
                no_change_count = 0
                last_height = new_height
            
            scroll_count += 1
        except Exception as e:
            log_error("SCROLL_ERROR", "Failed to scroll", str(e))
            break
    
    return scroll_count

# ============================================
# MAIN SCRAPING FUNCTION
# ============================================

def scrape_google_maps_real(keyword, location, max_results=10, extract_contact=True, progress_callback=None):
    """
    Production-ready Google Maps scraper
    Creates fresh driver instance to prevent session errors
    """
    businesses = []
    driver = None  # Initialize as None
    stats = {
        'total_found': 0,
        'successfully_extracted': 0,
        'google_maps_errors': 0,
        'website_scraped': 0,
        'website_errors': 0,
        'emails_found': 0,
        'social_found': 0
    }
    
    st.session_state.error_log = []
    
    try:
        # Get FRESH driver instance
        if progress_callback:
            progress_callback("🔧 Initializing Chrome browser...")
        
        driver = get_chrome_driver()
        
        if driver is None:
            error_msg = "❌ Failed to initialize Chrome driver.\n\nCheck deployment configuration."
            return pd.DataFrame(), error_msg, stats
        
        # Construct search URL
        search_query = f"{keyword} in {location}".replace(" ", "+")
        url = f"https://www.google.com/maps/search/{search_query}"
        
        if progress_callback:
            progress_callback(f"🌐 Step 1/2: Loading Google Maps for '{keyword}' in '{location}'...")
        
        try:
            driver.get(url)
            time.sleep(random.uniform(4, 6))
        except TimeoutException:
            error_msg = "⏱️ Google Maps page load timeout. Check internet connection."
            log_error("PAGE_TIMEOUT", "Failed to load Google Maps", url)
            return pd.DataFrame(), error_msg, stats
        except Exception as e:
            error_msg = f"❌ Failed to load Google Maps: {str(e)}"
            log_error("PAGE_LOAD", "Could not open Google Maps", str(e))
            return pd.DataFrame(), error_msg, stats
        
        if progress_callback:
            progress_callback("⏳ Step 1/2: Waiting for search results...")
        
        # Find results panel
        panel = None
        panel_selectors = [
            "//div[@role='feed']",
            "//div[contains(@class, 'm6QErb')]",
        ]
        
        for selector in panel_selectors:
            try:
                panel = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                if panel:
                    break
            except TimeoutException:
                continue
            except Exception as e:
                log_error("PANEL_LOCATE", "Error finding panel", str(e))
                continue
        
        if not panel:
            error_msg = f"❌ Could not find results for '{keyword}' in '{location}'.\n\nTry:\n• Broader keywords\n• Check spelling\n• Different location"
            log_error("NO_PANEL", "Results panel not found", f"Query: {keyword} in {location}")
            return pd.DataFrame(), error_msg, stats
        
        if progress_callback:
            progress_callback("📜 Step 1/2: Scrolling to load more results...")
        
        scroll_count = scroll_results_panel(driver, panel, max_scrolls=8)
        
        if progress_callback:
            progress_callback(f"✓ Completed {scroll_count} scrolls")
        
        time.sleep(2)
        
        # Find business elements
        business_elements = []
        link_selectors = [
            "//a[contains(@href, 'https://www.google.com/maps/place')]",
            "//a[contains(@class, 'hfpxzc')]",
        ]
        
        for selector in link_selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                if elements:
                    business_elements = elements
                    break
            except Exception as e:
                log_error("ELEMENT_FIND", "Error finding businesses", str(e))
                continue
        
        if not business_elements:
            error_msg = f"❌ No businesses found for '{keyword}' in '{location}'.\n\nSuggestions:\n• Use simpler keywords\n• Try nearby locations\n• Check if businesses exist"
            log_error("NO_RESULTS", "No business elements", f"Query: {keyword} in {location}")
            return pd.DataFrame(), error_msg, stats
        
        # Extract business links
        business_links = []
        for elem in business_elements:
            try:
                href = elem.get_attribute('href')
                if href and 'maps/place' in href:
                    business_links.append(elem)
                    if len(business_links) >= max_results:
                        break
            except StaleElementReferenceException:
                continue
            except:
                continue
        
        stats['total_found'] = len(business_links)
        
        if not business_links:
            error_msg = "❌ Found results but couldn't extract links. Google Maps layout may have changed."
            log_error("NO_LINKS", "Could not extract business links", "Elements stale")
            return pd.DataFrame(), error_msg, stats
        
        if progress_callback:
            progress_callback(f"📊 Step 1/2: Found {len(business_links)} businesses. Extracting details...")
        
        # Extract details for each business
        for idx, link in enumerate(business_links):
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
                time.sleep(0.6)
                
                driver.execute_script("arguments[0].click();", link)
                time.sleep(random.uniform(2.5, 4))
                
                # Extract name
                name_xpaths = [
                    "//h1[contains(@class, 'DUwDvf')]",
                    "//h1[@class='fontHeadlineLarge']",
                    "//div[@role='main']//h1"
                ]
                name = "N/A"
                for xpath in name_xpaths:
                    name = extract_text_safe(driver, xpath)
                    if name != "N/A":
                        break
                
                if name == "N/A":
                    log_error("NAME_EXTRACT", f"Business #{idx+1}: No name", "All XPaths failed")
                    stats['google_maps_errors'] += 1
                    continue
                
                phone = extract_phone_number(driver, name)
                address = extract_address(driver, name)
                website = extract_website(driver, name)
                
                # Extract category
                category = keyword
                category_xpaths = [
                    "//button[contains(@class, 'DkEaL')]",
                    "//button[@jsaction='pane.rating.category']"
                ]
                for xpath in category_xpaths:
                    cat = extract_text_safe(driver, xpath)
                    if cat != "N/A":
                        category = cat
                        break
                
                rating = extract_text_safe(driver, "//div[contains(@class, 'F7nice')]//span[@aria-hidden='true']")
                
                reviews = extract_text_safe(driver, "//div[contains(@class, 'F7nice')]//span[@aria-label]", "aria-label")
                if reviews != "N/A" and "reviews" in reviews:
                    reviews = reviews.split()[0].replace(',', '')
                
                business = {
                    'Business Name': name,
                    'Email ID': 'N/A',
                    'Phone Number': phone,
                    'Location / Address': address,
                    'Business Category': category,
                    'Website URL': website,
                    'Social Media Profiles': 'N/A',
                    'Rating': rating,
                    'Reviews': reviews
                }
                
                businesses.append(business)
                stats['successfully_extracted'] += 1
                
                if progress_callback:
                    progress_callback(f"✓ Step 1/2: Extracted {idx + 1}/{len(business_links)}: {name}")
                
            except StaleElementReferenceException:
                log_error("STALE_ELEMENT", f"Business #{idx+1}: Stale element", "Skip")
                stats['google_maps_errors'] += 1
                continue
            except Exception as e:
                log_error("EXTRACT_ERROR", f"Business #{idx+1}: Error", str(e))
                stats['google_maps_errors'] += 1
                continue
        
        if not businesses:
            error_msg = f"❌ Extracted 0 of {len(business_links)} businesses. See error log."
            return pd.DataFrame(), error_msg, stats
        
        # Step 2: Extract emails and social media
        if extract_contact and businesses:
            if progress_callback:
                progress_callback(f"🌐 Step 2/2: Scraping websites for {len(businesses)} businesses...")
            
            for idx, business in enumerate(businesses):
                website = business.get('Website URL', 'N/A')
                name = business.get('Business Name', 'Unknown')
                
                if website != 'N/A':
                    if progress_callback:
                        progress_callback(f"🔍 Step 2/2: Scraping {idx + 1}/{len(businesses)}: {name[:30]}")
                    
                    contact_info = scrape_website_for_contact_info(website, name)
                    stats['website_scraped'] += 1
                    
                    if contact_info['emails']:
                        business['Email ID'] = ', '.join(contact_info['emails'])
                        stats['emails_found'] += 1
                    else:
                        if contact_info['error']:
                            stats['website_errors'] += 1
                    
                    if contact_info['social_media']:
                        social_links = []
                        for platform, url in contact_info['social_media'].items():
                            social_links.append(f"{platform.capitalize()}: {url}")
                        business['Social Media Profiles'] = ' | '.join(social_links)
                        stats['social_found'] += 1
                    
                    time.sleep(random.uniform(1, 2))
                else:
                    if progress_callback:
                        progress_callback(f"⊗ Step 2/2: Skipped {idx + 1}/{len(businesses)}: No website")
        
        st.session_state.extraction_stats = stats
        
        if businesses:
            return pd.DataFrame(businesses), None, stats
        else:
            error_msg = "✓ Loaded Google Maps but extracted no details. See error log."
            return pd.DataFrame(), error_msg, stats
        
    except Exception as e:
        error_msg = f"❌ Critical error:\n{type(e).__name__}: {str(e)}"
        log_error("CRITICAL", "Fatal error", f"{type(e).__name__}: {str(e)}")
        return pd.DataFrame(), error_msg, stats
    
    finally:
        # IMPORTANT: Always quit driver to clean up resources
        if driver:
            try:
                driver.quit()
                logger.info("✅ Chrome driver closed successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error closing driver: {str(e)}")

# ============================================
# STREAMLIT UI
# ============================================

st.title("🎯 Lead Generation Automation System")
st.markdown("**Production Ready** | Optimized for Streamlit Cloud & Render")

st.info("📊 **2-Step Process:** Extract from Google Maps (30-60s) → Scrape websites for contact info (5-10s per business)")

# Display error log
display_error_log()

st.divider()

# ============================================
# INPUT FIELDS
# ============================================
st.subheader("🔍 Search Parameters")

col1, col2 = st.columns(2)

with col1:
    keyword = st.text_input(
        "Search Keyword",
        placeholder="e.g., Coffee Shop, Dental Clinic, Gym",
        help="Be specific for better results"
    )

with col2:
    location = st.text_input(
        "Location",
        placeholder="e.g., Mumbai, Bangalore, Delhi",
        help="City name or area"
    )

num_results = st.slider(
    "Number of Results",
    min_value=3,
    max_value=15,
    value=8,
    help="Recommended: 5-10 results for optimal performance"
)

extract_contact = st.checkbox(
    "Extract Email and Social Media (adds 5-10s per business)",
    value=True,
    help="Uncheck for faster Google Maps-only extraction"
)

if extract_contact:
    st.caption(f"⏱️ Estimated time: {num_results * 8}-{num_results * 12} seconds")
else:
    st.caption(f"⏱️ Estimated time: {num_results * 4}-{num_results * 6} seconds")

st.divider()

# ============================================
# EXTRACTION BUTTON
# ============================================
st.subheader("🚀 Start Extraction")

col1, col2, col3 = st.columns([1, 1, 1])

with col2:
    start_button = st.button(
        "🚀 Start Extraction", 
        type="primary", 
        use_container_width=True,
        disabled=st.session_state.is_scraping
    )

if start_button:
    if not keyword or not location:
        st.error("❌ Please enter both keyword and location")
    else:
        st.session_state.is_scraping = True
        
        progress_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(message):
                status_text.text(message)
                if "Step 1/2" in message:
                    if "Initializing" in message:
                        progress_bar.progress(5)
                    elif "Loading" in message:
                        progress_bar.progress(15)
                    elif "Scrolling" in message:
                        progress_bar.progress(30)
                    elif "Extracting" in message or "Extracted" in message:
                        progress_bar.progress(50)
                elif "Step 2/2" in message:
                    if "Starting" in message or "Scraping websites" in message:
                        progress_bar.progress(55)
                    else:
                        try:
                            parts = message.split(":")
                            if len(parts) > 1:
                                nums = parts[1].split("/")
                                if len(nums) == 2:
                                    current = int(nums[0].strip().split()[-1])
                                    total = int(nums[1].split()[0])
                                    progress = 55 + int((current / total) * 40)
                                    progress_bar.progress(min(progress, 95))
                        except:
                            pass
            
            start_time = time.time()
            df, error, stats = scrape_google_maps_real(
                keyword, 
                location, 
                num_results, 
                extract_contact, 
                update_progress
            )
            elapsed_time = time.time() - start_time
            
            progress_bar.progress(100)
            
            if error:
                st.error(error)
                status_text.text(f"⏱️ Failed after {elapsed_time:.1f} seconds")
                
                if stats['total_found'] > 0:
                    st.warning(f"**Partial Results:** Found {stats['total_found']} but extracted {stats['successfully_extracted']}")
                    
            elif df is not None and not df.empty:
                st.session_state.extracted_data = df
                status_text.empty()
                progress_bar.empty()
                
                email_count = len(df[df['Email ID'] != 'N/A'])
                social_count = len(df[df['Social Media Profiles'] != 'N/A'])
                
                st.success(f"✅ Successfully extracted **{len(df)} businesses** in {elapsed_time:.1f}s")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total", stats['successfully_extracted'])
                with col2:
                    st.metric("Emails", email_count, delta=f"{email_count/len(df)*100:.0f}%")
                with col3:
                    st.metric("Social", social_count, delta=f"{social_count/len(df)*100:.0f}%")
                with col4:
                    st.metric("Errors", stats['google_maps_errors'] + stats['website_errors'])
                
                st.balloons()
                
            else:
                st.warning(f"⚠️ No results for '{keyword}' in '{location}'.\n\nTry broader keywords or different location.")
                status_text.text(f"⏱️ Completed in {elapsed_time:.1f}s (0 results)")
        
        display_error_log()
        
        st.session_state.is_scraping = False
        st.rerun()

st.divider()

# ============================================
# DISPLAY RESULTS
# ============================================
st.subheader("📊 Extracted Leads")

if st.session_state.extracted_data is not None:
    df = st.session_state.extracted_data
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📍 Total Leads", len(df))
    with col2:
        email_count = len(df[df['Email ID'] != 'N/A'])
        st.metric("📧 With Email", email_count, delta=f"{email_count/len(df)*100:.0f}%")
    with col3:
        phone_count = len(df[df['Phone Number'] != 'N/A'])
        st.metric("📞 With Phone", phone_count, delta=f"{phone_count/len(df)*100:.0f}%")
    with col4:
        social_count = len(df[df['Social Media Profiles'] != 'N/A'])
        st.metric("🌐 With Social", social_count, delta=f"{social_count/len(df)*100:.0f}%")
    
    st.write("")
    st.dataframe(df, use_container_width=True, height=400)
    
    if st.session_state.extraction_stats:
        stats = st.session_state.extraction_stats
        with st.expander("📈 Extraction Statistics", expanded=False):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Google Maps:**")
                st.write(f"- Found: {stats['total_found']}")
                st.write(f"- Extracted: {stats['successfully_extracted']}")
                st.write(f"- Errors: {stats['google_maps_errors']}")
            
            with col2:
                st.write("**Website Scraping:**")
                st.write(f"- Scraped: {stats['website_scraped']}")
                st.write(f"- Emails: {stats['emails_found']}")
                st.write(f"- Social: {stats['social_found']}")
    
else:
    st.info("👆 Enter search parameters and click 'Start Extraction'")
    
    empty_df = pd.DataFrame(columns=[
        'Business Name', 'Email ID', 'Phone Number',
        'Location / Address', 'Business Category',
        'Website URL', 'Social Media Profiles'
    ])
    st.dataframe(empty_df, use_container_width=True, height=200)

st.divider()

# ============================================
# EXPORT SECTION
# ============================================
st.subheader("💾 Export Data")

if st.session_state.extracted_data is not None:
    df = st.session_state.extracted_data
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_keyword = re.sub(r'[^\w\s-]', '', keyword).strip().replace(' ', '_').lower() if keyword else 'leads'
    clean_location = re.sub(r'[^\w\s-]', '', location).strip().replace(' ', '_').lower() if location else 'location'
    filename = f"leads_{clean_keyword}_{clean_location}_{timestamp}.csv"
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        csv = df.to_csv(index=False, encoding='utf-8-sig')
        
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=filename,
            mime='text/csv',
            use_container_width=True,
            type="primary"
        )
    
    email_count = len(df[df['Email ID'] != 'N/A'])
    phone_count = len(df[df['Phone Number'] != 'N/A'])
    st.success(f"✅ Ready: {filename}")
    st.caption(f"📊 {len(df)} records | 📧 {email_count} emails | 📞 {phone_count} phones")
    
else:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.button("📥 Download CSV", disabled=True, use_container_width=True)
    st.caption("⚠️ Extract leads first")

# Footer
st.divider()
st.caption("🚀 Lead Generation System v3.0 - Production Ready")
st.caption("⚡ Use responsibly | Respect rate limits and Terms of Service")

# Sidebar
with st.sidebar:
    st.header("🔧 System Info")
    
    if st.session_state.extraction_stats:
        st.json(st.session_state.extraction_stats)
    
    st.write("**Session:**")
    st.write(f"- Data: {st.session_state.extracted_data is not None}")
    st.write(f"- Errors: {len(st.session_state.error_log)}")
    st.write(f"- Scraping: {st.session_state.is_scraping}")
    
    if st.button("🗑️ Clear All"):
        st.session_state.extracted_data = None
        st.session_state.error_log = []
        st.session_state.extraction_stats = {}
        st.rerun()

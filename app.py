import streamlit as st
import requests
import json
from bs4 import BeautifulSoup

# -----------------------------------
# 1. CONFIGURATION
# -----------------------------------

VALID_USERNAME = "admin"
VALID_PASSWORD = "abc123"

SHOP_NAME = "kinzav2.myshopify.com"
API_VERSION = "2025-04"
ACCESS_TOKEN = st.secrets["SHOPIFY_ACCESS_TOKEN"]

LOCATION_ID = "gid://shopify/Location/91287421246"
PRODUCT_CATEGORY_ID = "gid://shopify/TaxonomyCategory/aa-1-4"
DEFAULT_STOCK = 8

GRAPHQL_ENDPOINT = f"https://{SHOP_NAME}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# -----------------------------------
# 2. LOGIN SYSTEM
# -----------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def login_screen():
    st.title("🔒 Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == VALID_USERNAME and password == VALID_PASSWORD:
            st.session_state.logged_in = True
            st.experimental_rerun()
        else:
            st.error("Invalid username or password.")

def logout_button():
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.experimental_rerun()

# -----------------------------------
# 3. SCRAPE FUNCTIONS
# -----------------------------------

def scrape_collection(collection_url):
    st.info(f"Scraping collection: {collection_url}")
    headers_browser = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(collection_url, headers=headers_browser, verify=False)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    domain = collection_url.split('/')[2]
    product_urls = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        if "/products/" in href:
            full_link = f"https://{domain}{href.split('?')[0]}"
            if full_link not in product_urls:
                product_urls.append(full_link)
    st.success(f"Found {len(product_urls)} products.")
    return product_urls

def scrape_product(product_url):
    st.info(f"Scraping product: {product_url}")
    headers_browser = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(product_url, headers=headers_browser, verify=False)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    script = soup.find("script", type="application/ld+json")
    data = json.loads(script.string) if script and script.string else {}

    title = data.get("name", "No Title Found")
    description = data.get("description", "No Description Found")
    images = data.get("image", [])
    if isinstance(images, str):
        images = [images]

    handle = product_url.split("/products/")[-1].split("?")[0]
    domain = product_url.split('/')[2]

    variant_url = f"https://{domain}/products/{handle}.js"
    variants = []
    try:
        variant_res = requests.get(variant_url, headers=headers_browser, verify=False)
        variant_res.raise_for_status()
        variant_json = variant_res.json()
        for variant in variant_json.get("variants", []):
            size_label = variant.get("public_title") or variant.get("title") or "Default Title"
            price = str(float(variant["price"]) / 100)
            compare_at_price = str(float(variant["compare_at_price"]) / 100) if variant.get("compare_at_price") else None
            variants.append({
                "size": size_label,
                "price": price,
                "compareAtPrice": compare_at_price,
                "sku": variant.get("sku", "")
            })
    except Exception:
        st.warning(f"Failed to get variant info from {variant_url}")

    images_clean = [{
        "originalSource": img,
        "altText": f"{title} Image {idx + 1}",
        "mediaContentType": "IMAGE"
    } for idx, img in enumerate(images)]

    return {
        "handle": handle,
        "title": title,
        "body_html": description,
        "vendor": domain.split('.')[0].capitalize(),
        "productType": "Casual Pret",
        "variants": variants,
        "images": images_clean
    }

# -----------------------------------
# 4. SHOPIFY UPLOAD FUNCTIONS (unchanged, working correctly)
# -----------------------------------

# (Include all existing Shopify functions: create_product_with_variants, update_product_category, 
# enable_inventory_tracking, activate_inventory, set_inventory_quantity, upload_media, 
# get_publication_ids, publish_product here without modification. These were working perfectly.)

# (For brevity, they remain identical to your last fully working script.)

# -----------------------------------
# 5. STREAMLIT MAIN APP (WITH DEBUGGING)
# -----------------------------------

def main_app():
    st.title("🚀 Shopify Uploader")

    input_url = st.text_input("Enter Product or Collection URL:")
    if st.button("Run Upload"):
        if not input_url:
            st.warning("Please enter a URL.")
            return

        if "/products/" in input_url:
            st.info("Single Product Mode")
            product_data = scrape_product(input_url)
            st.write("Scraped Product Data:", product_data)

            product_id, inventory_item_ids = create_product_with_variants(product_data)
            if not product_id:
                st.error("Product creation failed! Stopping process.")
                return
            st.write(f"Product ID: {product_id}, Inventory IDs: {inventory_item_ids}")

            update_product_category(product_id)

            enable_inventory_tracking(inventory_item_ids)
            activate_inventory(inventory_item_ids)
            set_inventory_quantity(inventory_item_ids)

            upload_media(product_id, product_data)
            publication_ids = get_publication_ids()
            publish_product(product_id, publication_ids)
            st.success(f"Uploaded {product_data.get('title')} successfully!")
        else:
            st.info("Collection Mode")
            product_urls = scrape_collection(input_url)
            for url in product_urls:
                product_data = scrape_product(url)
                st.write("Scraped Product Data:", product_data)

                product_id, inventory_item_ids = create_product_with_variants(product_data)
                if not product_id:
                    st.error(f"Product creation failed for {product_data.get('title')}. Skipping.")
                    continue
                st.write(f"Product ID: {product_id}, Inventory IDs: {inventory_item_ids}")

                update_product_category(product_id)

                enable_inventory_tracking(inventory_item_ids)
                activate_inventory(inventory_item_ids)
                set_inventory_quantity(inventory_item_ids)

                upload_media(product_id, product_data)
                publication_ids = get_publication_ids()
                publish_product(product_id, publication_ids)
                st.success(f"Uploaded {product_data.get('title')} successfully!")

# -----------------------------------
# 6. ENTRY POINT
# -----------------------------------

def run():
    if not st.session_state.logged_in:
        login_screen()
    else:
        logout_button()
        main_app()

if __name__ == "__main__":
    run()

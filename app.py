import streamlit as st
import requests
import json
from bs4 import BeautifulSoup

################################
# 1. BASIC CREDENTIALS
################################
# Replace with your desired username & password
VALID_USERNAME = "admin"
VALID_PASSWORD = "abc123"

# Shopify Settings (replace with your real data)
SHOP_NAME = "kinzav2.myshopify.com"
ACCESS_TOKEN = st.secrets["SHOPIFY_ACCESS_TOKEN"]
API_VERSION = "2025-04"
LOCATION_ID = "gid://shopify/Location/91287421246"
PRODUCT_CATEGORY_ID = "gid://shopify/TaxonomyCategory/aa-1-4"
DEFAULT_STOCK = 8

# GraphQL Endpoint & Headers
GRAPHQL_ENDPOINT = f"https://{SHOP_NAME}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

################################
# 2. LOGIN LOGIC
################################
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def login_screen():
    st.title("Login")
    user_input = st.text_input("Username")
    pass_input = st.text_input("Password", type="password")
    if st.button("Login"):
        if user_input == VALID_USERNAME and pass_input == VALID_PASSWORD:
            st.session_state.logged_in = True
            st.experimental_rerun()
        else:
            st.error("Invalid username or password")

def logout_button():
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.experimental_rerun()

################################
# 3. SCRAPE FUNCTIONS
################################
def scrape_collection(collection_url):
    st.info(f"Scraping collection: {collection_url}")
    headers_browser = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(collection_url, headers=headers_browser)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    product_urls = []
    domain = collection_url.split('/')[2]
    for link in soup.find_all('a', href=True):
        href = link['href']
        if "/products/" in href:
            clean_href = href.split('?')[0]
            product_link = f"https://{domain}{clean_href}"
            if product_link not in product_urls:
                product_urls.append(product_link)
    st.success(f"Found {len(product_urls)} products.")
    return product_urls

def scrape_product(product_url):
    st.info(f"Scraping product page: {product_url}")
    headers_browser = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(product_url, headers=headers_browser)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    script = soup.find("script", type="application/ld+json")
    data = {}
    if script and script.string:
        data = json.loads(script.string)

    title = data.get("name", "No Title Found")
    description = data.get("description", "No Description Found")
    images = data.get("image", [])
    if isinstance(images, str):
        images = [images]

    handle = product_url.split("/products/")[-1].split('?')[0]

    # variant .js
    domain = product_url.split('/')[2]
    variant_url = f"https://{domain}/products/{handle}.js"
    variant_data = []
    try:
        variant_res = requests.get(variant_url, headers=headers_browser)
        variant_res.raise_for_status()
        variant_json = variant_res.json()
        variant_data = variant_json.get("variants", [])
    except:
        st.warning(f"Failed to get variant data from {variant_url}")

    variants = []
    for v in variant_data:
        size_label = v.get("public_title") or v.get("title") or "Default Title"
        price = str(float(v["price"]) / 100)
        compare_at_price = None
        if v.get("compare_at_price"):
            compare_at_price = str(float(v["compare_at_price"]) / 100)
        variants.append({
            "size": size_label,
            "price": price,
            "compareAtPrice": compare_at_price,
            "sku": v.get("sku", "")
        })

    images_clean = [{
        "originalSource": img,
        "altText": f"{title} Image {idx+1}",
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

################################
# 4. SHOPIFY CREATE/UPLOAD FUNCTIONS
################################
def create_product_with_variants(product_data):
    query = """
    mutation productSet($product: ProductSetInput!) {
      productSet(input: $product) {
        product {
          id
          title
          handle
          variants(first: 50) {
            edges {
              node {
                id
                inventoryItem {
                  id
                }
              }
            }
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    sizes = list({v["size"] for v in product_data["variants"]})
    product_input = {
        "title": product_data["title"],
        "handle": product_data["handle"],
        "descriptionHtml": product_data["body_html"],
        "vendor": product_data["vendor"],
        "productType": product_data["productType"],
        "productOptions": [
            {
                "name": "Size",
                "position": 1,
                "values": [{"name": s} for s in sizes]
            }
        ],
        "variants": []
    }
    for v in product_data["variants"]:
        variant_entry = {
            "price": v["price"],
            "optionValues": [{"optionName": "Size", "name": v["size"]}]
        }
        if v["compareAtPrice"]:
            variant_entry["compareAtPrice"] = v["compareAtPrice"]
        if v["sku"]:
            variant_entry["sku"] = v["sku"]
        product_input["variants"].append(variant_entry)

    payload = {"query": query, "variables": {"product": product_input}}
    response = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload)
    resp_json = response.json()

    user_errors = resp_json["data"]["productSet"]["userErrors"]
    if user_errors:
        st.error(f"Error creating product: {user_errors}")
        return None, []
    product = resp_json["data"]["productSet"]["product"]
    if not product:
        st.error("No product returned in response.")
        return None, []
    product_id = product["id"]
    inventory_items = [
        edge["node"]["inventoryItem"]["id"]
        for edge in product["variants"]["edges"]
    ]
    return product_id, inventory_items

def update_product_category(product_id):
    query = """
    mutation productUpdate($product: ProductUpdateInput!) {
      productUpdate(product: $product) {
        product { id }
        userErrors { field message }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "product": {
                "id": product_id,
                "category": PRODUCT_CATEGORY_ID
            }
        }
    }
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload)

def enable_tracking_on_inventory(inventory_item_ids):
    query = """
    mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
      inventoryItemUpdate(id: $id, input: $input) {
        inventoryItem { id tracked }
        userErrors { field message }
      }
    }
    """
    for item_id in inventory_item_ids:
        payload = {"query": query, "variables": {"id": item_id, "input": {"tracked": True}}}
        requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload)

def activate_inventory_items(inventory_item_ids):
    query = """
    mutation inventoryActivate($inventoryItemId: ID!, $locationId: ID!) {
      inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId) {
        userErrors { field message }
      }
    }
    """
    for item_id in inventory_item_ids:
        payload = {"query": query, "variables": {"inventoryItemId": item_id, "locationId": LOCATION_ID}}
        requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload)

def set_inventory(inventory_item_ids):
    query = """
    mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
      inventorySetQuantities(input: $input) {
        userErrors { field message }
      }
    }
    """
    changes = [{
        "inventoryItemId": item_id,
        "locationId": LOCATION_ID,
        "quantity": DEFAULT_STOCK
    } for item_id in inventory_item_ids]
    payload = {
        "query": query,
        "variables": {
            "input": {
                "name": "available",
                "reason": "correction",
                "ignoreCompareQuantity": True,
                "quantities": changes
            }
        }
    }
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload)

def upload_media(product_id, product_data):
    query = """
    mutation productCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $productId, media: $media) {
        media { id status }
        userErrors { field message }
      }
    }
    """
    media_list = [{
        "originalSource": img["originalSource"],
        "mediaContentType": img["mediaContentType"],
        "alt": img.get("altText", "")
    } for img in product_data["images"]]
    if not media_list:
        return
    payload = {"query": query, "variables": {"productId": product_id, "media": media_list}}
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload)

################################
# 5. MAIN APP FUNCTION
################################
def main_app():
    st.title("Shopify Product Uploader")
    st.write("Enter a single Product URL or a Collection URL to scrape & upload products.")
    
    input_url = st.text_input("Product or Collection URL:")
    if st.button("Run Upload"):
        if not input_url:
            st.warning("Please enter a valid URL.")
            return
        
        # If the URL includes /products/, treat it as a single product
        if "/products/" in input_url:
            st.write("Uploading single product...")
            product_data = scrape_product(input_url)
            product_id, inventory_items = create_product_with_variants(product_data)
            if product_id:
                update_product_category(product_id)
                enable_tracking_on_inventory(inventory_items)
                activate_inventory_items(inventory_items)
                set_inventory(inventory_items)
                upload_media(product_id, product_data)
                st.success(f"Uploaded {product_data.get('title', '')} successfully!")
        else:
            # Otherwise, treat it as a collection
            st.write("Scraping all products from collection...")
            product_urls = scrape_collection(input_url)
            for url in product_urls:
                st.write(f"Processing: {url}")
                product_data = scrape_product(url)
                product_id, inventory_items = create_product_with_variants(product_data)
                if product_id:
                    update_product_category(product_id)
                    enable_tracking_on_inventory(inventory_items)
                    activate_inventory_items(inventory_items)
                    set_inventory(inventory_items)
                    upload_media(product_id, product_data)
                    st.success(f"Uploaded {product_data.get('title', '')}")

################################
# 6. STREAMLIT ENTRY POINT
################################
def run():
    # If not logged in, show login screen
    if not st.session_state.logged_in:
        login_screen()
    else:
        # Otherwise show logout & main interface
        logout_button()
        main_app()

if __name__ == "__main__":
    run()

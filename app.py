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

# 📦 Fetch Shopify Collections
def fetch_collections():
    query = """
    {
      collections(first: 100) {
        edges {
          node { id title }
        }
      }
    }
    """
    response = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": query}, verify=False)
    return response.json()["data"]["collections"]["edges"]

# -----------------------------------
# 4. SHOPIFY UPLOAD FUNCTIONS
# -----------------------------------

def create_product_with_variants(product_data):
    query = """
    mutation productSet($product: ProductSetInput!) {
      productSet(input: $product) {
        product {
          id
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
        "productOptions": [{"name": "Size", "position": 1, "values": [{"name": s} for s in sizes]}],
        "variants": []
    }
    for v in product_data["variants"]:
        entry = {
            "price": v["price"],
            "optionValues": [{"optionName": "Size", "name": v["size"]}]
        }
        if v["compareAtPrice"]:
            entry["compareAtPrice"] = v["compareAtPrice"]
        if v["sku"]:
            entry["sku"] = v["sku"]
        product_input["variants"].append(entry)

    payload = {"query": query, "variables": {"product": product_input}}
    response = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)
    data = response.json()

    if data.get("errors") or data["data"]["productSet"]["userErrors"]:
        st.error(f"Error creating product: {data}")
        return None, []

    product_id = data["data"]["productSet"]["product"]["id"]
    inventory_items = [edge["node"]["inventoryItem"]["id"] for edge in data["data"]["productSet"]["product"]["variants"]["edges"]]
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
    payload = {"query": query, "variables": {"product": {"id": product_id, "category": PRODUCT_CATEGORY_ID}}}
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)

def enable_inventory_tracking(inventory_item_ids):
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
        requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)

def activate_inventory(inventory_item_ids):
    query = """
    mutation inventoryActivate($inventoryItemId: ID!, $locationId: ID!) {
      inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId) {
        userErrors { field message }
      }
    }
    """
    for item_id in inventory_item_ids:
        payload = {"query": query, "variables": {"inventoryItemId": item_id, "locationId": LOCATION_ID}}
        requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)

def set_inventory_quantity(inventory_item_ids):
    query = """
    mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
      inventorySetQuantities(input: $input) {
        userErrors { field message }
      }
    }
    """
    changes = [{"inventoryItemId": item_id, "locationId": LOCATION_ID, "quantity": DEFAULT_STOCK} for item_id in inventory_item_ids]
    payload = {"query": query, "variables": {"input": {"name": "available", "reason": "correction", "ignoreCompareQuantity": True, "quantities": changes}}}
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)

def upload_media(product_id, product_data):
    query = """
    mutation productCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $productId, media: $media) {
        media { id status }
        userErrors { field message }
      }
    }
    """
    media_list = [{"originalSource": img["originalSource"], "mediaContentType": img["mediaContentType"], "alt": img.get("altText", "")} for img in product_data["images"]]
    if not media_list:
        return
    payload = {"query": query, "variables": {"productId": product_id, "media": media_list}}
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)

# 📋 SALES CHANNELS - New

def get_publication_ids():
    query = """
    {
      publications(first: 20) {
        edges {
          node {
            id
          }
        }
      }
    }
    """
    response = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": query}, verify=False)
    return [edge["node"]["id"] for edge in response.json()["data"]["publications"]["edges"]]

def publish_product(product_id, publication_ids):
    query = """
    mutation PublishProduct($input: ProductPublishInput!) {
      productPublish(input: $input) {
        product {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "input": {
                "id": product_id,
                "productPublications": [{"publicationId": pub_id} for pub_id in publication_ids]
            }
        }
    }
    requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False)

# -----------------------------------
# 6. STREAMLIT MAIN APP
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
            product_id, inventory_item_ids = create_product_with_variants(product_data)
            if product_id:
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
                product_id, inventory_item_ids = create_product_with_variants(product_data)
                if product_id:
                    update_product_category(product_id)
                    enable_inventory_tracking(inventory_item_ids)
                    activate_inventory(inventory_item_ids)
                    set_inventory_quantity(inventory_item_ids)
                    upload_media(product_id, product_data)
                    publication_ids = get_publication_ids()
                    publish_product(product_id, publication_ids)
                    st.success(f"Uploaded {product_data.get('title')} successfully!")

# -----------------------------------
# 7. ENTRY POINT
# -----------------------------------

def run():
    if not st.session_state.logged_in:
        login_screen()
    else:
        logout_button()
        main_app()

if __name__ == "__main__":
    run()

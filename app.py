import streamlit as st
import requests
import json
import random
import string
from bs4 import BeautifulSoup

# ---------------------------
# CONFIGURATION
# ---------------------------

VALID_USERNAME = "admin"
VALID_PASSWORD = "abc123"

SHOP_NAME = "kinzav2.myshopify.com"
API_VERSION = "2025-04"
ACCESS_TOKEN = st.secrets["SHOPIFY_ACCESS_TOKEN"]

LOCATION_ID = "gid://shopify/Location/91287421246"
PRODUCT_CATEGORY_ID = "gid://shopify/TaxonomyCategory/aa-1-4"
DEFAULT_STOCK = 8

GRAPHQL_ENDPOINT = f"https://{SHOP_NAME}/admin/api/{API_VERSION}/graphql.json"
REST_ENDPOINT = f"https://{SHOP_NAME}/admin/api/{API_VERSION}"
HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# ---------------------------
# LOGIN SYSTEM
# ---------------------------

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

# ---------------------------
# HELPER FUNCTIONS
# ---------------------------

def generate_random_suffix(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def get_collections():
    url = f"{REST_ENDPOINT}/custom_collections.json?limit=250"
    res = requests.get(url, headers=HEADERS, verify=False).json()
    return {col["title"]: col["id"] for col in res.get("custom_collections", [])}

def add_product_to_collections(product_id, collection_ids):
    for col_id in collection_ids:
        payload = {"collect": {"product_id": product_id, "collection_id": col_id}}
        requests.post(f"{REST_ENDPOINT}/collects.json", headers=HEADERS, json=payload, verify=False)

def get_publication_ids():
    query = "{ publications(first:10) { edges { node { id } } } }"
    res = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": query}, verify=False).json()
    return [edge["node"]["id"] for edge in res["data"]["publications"]["edges"]]

def publish_product(product_id, publication_ids):
    query = """
    mutation publish($input: ProductPublishInput!) {
      productPublish(input: $input) {
        product { id }
        userErrors { field message }
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

# ---------------------------
# SCRAPING FUNCTIONS
# ---------------------------

def scrape_collection(url):
    st.info(f"Scraping collection: {url}")
    res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, verify=False)
    soup = BeautifulSoup(res.text, "html.parser")
    domain = url.split('/')[2]
    product_urls = []
    for link in soup.select('a[href*="/products/"]'):
        full_url = f"https://{domain}{link['href'].split('?')[0]}"
        if full_url not in product_urls:
            product_urls.append(full_url)
    st.success(f"Found {len(product_urls)} products.")
    return product_urls

def scrape_product(url):
    st.info(f"Scraping product: {url}")
    res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, verify=False)
    soup = BeautifulSoup(res.text, "html.parser")
    data = json.loads(soup.find("script", type="application/ld+json").string or "{}")

    title = data.get("name", "No Title")
    description = data.get("description", "No Description")
    images = data.get("image", [])
    if isinstance(images, str): images = [images]

    handle_base = url.split("/products/")[-1].split("?")[0]
    handle = f"{handle_base}-{generate_random_suffix()}"
    domain = url.split('/')[2]

    variants = []
    variant_res = requests.get(f"https://{domain}/products/{handle_base}.js", verify=False).json()
    for var in variant_res.get("variants", []):
        variants.append({
            "size": var.get("title", "Default Title"),
            "price": str(float(var["price"]) / 100),
            "compareAtPrice": str(float(var["compare_at_price"]) / 100) if var.get("compare_at_price") else None,
            "sku": var.get("sku", "")
        })

    return {
        "handle": handle, "title": title, "body_html": description,
        "vendor": domain.split('.')[0].capitalize(),
        "productType": "Casual Pret", "variants": variants,
        "images": [{"originalSource":img, "altText":title} for img in images]
    }

# ---------------------------
# SHOPIFY PRODUCT CREATION
# ---------------------------

def create_product(product_data):
    query = """
    mutation($product: ProductSetInput!) {
      productSet(input:$product) {
        product { id variants(first:10){edges{node{id inventoryItem{id}}}} }
        userErrors { message }
      }
    }
    """
    sizes = list({v["size"] for v in product_data["variants"]})
    product_input = {
        "title": product_data["title"], "handle": product_data["handle"],
        "descriptionHtml": product_data["body_html"], "vendor": product_data["vendor"],
        "productType": product_data["productType"],
        "productOptions": [{"name":"Size","position":1,"values":[{"name":s} for s in sizes]}],
        "variants": [{"price":v["price"],"optionValues":[{"optionName":"Size","name":v["size"]}],
                      "compareAtPrice":v["compareAtPrice"],"sku":v["sku"]} for v in product_data["variants"]]
    }
    payload = {"query":query,"variables":{"product":product_input}}
    res = requests.post(GRAPHQL_ENDPOINT,headers=HEADERS,json=payload,verify=False).json()
    product_id = res["data"]["productSet"]["product"]["id"]
    inv_ids = [edge["node"]["inventoryItem"]["id"] for edge in res["data"]["productSet"]["product"]["variants"]["edges"]]
    return product_id, inv_ids

def update_product_category(product_id):
    query = "mutation productUpdate($product:ProductUpdateInput!){productUpdate(product:$product){product{id}}}"
    requests.post(GRAPHQL_ENDPOINT,headers=HEADERS,json={"query":query,"variables":{"product":{"id":product_id,"category":PRODUCT_CATEGORY_ID}}},verify=False)

def set_inventory(inv_ids):
    for inv_id in inv_ids:
        requests.post(GRAPHQL_ENDPOINT,headers=HEADERS,json={"query":"mutation($id:ID!,$input:InventoryItemInput!){inventoryItemUpdate(id:$id,input:$input){inventoryItem{id}}}","variables":{"id":inv_id,"input":{"tracked":True}}},verify=False)
        requests.post(GRAPHQL_ENDPOINT,headers=HEADERS,json={"query":"mutation($input:InventorySetQuantitiesInput!){inventorySetQuantities(input:$input){userErrors{message}}}","variables":{"input":{"quantities":[{"inventoryItemId":inv_id,"locationId":LOCATION_ID,"quantity":DEFAULT_STOCK}],"ignoreCompareQuantity":True}}},verify=False)

def upload_media(product_id,images):
    requests.post(GRAPHQL_ENDPOINT,headers=HEADERS,json={"query":"mutation($productId:ID!,$media:[CreateMediaInput!]!){productCreateMedia(productId:$productId,media:$media){media{id}}}","variables":{"productId":product_id,"media":images}},verify=False)

# ---------------------------
# MAIN APP
# ---------------------------

def main_app():
    st.title("🚀 Shopify Uploader")
    cols = get_collections()
    selected = st.multiselect("Collections:",list(cols))
    url = st.text_input("Product/Collection URL:")
    if st.button("Upload"):
        urls = [url] if "/products/" in url else scrape_collection(url)
        for u in urls:
            data = scrape_product(u)
            pid,inv_ids = create_product(data)
            update_product_category(pid)
            set_inventory(inv_ids)
            upload_media(pid,data["images"])
            publish_product(pid,get_publication_ids())
            add_product_to_collections(pid.split('/')[-1],[cols[s] for s in selected])
            st.success(f"✅ {data['title']} uploaded!")

# ---------------------------
# ENTRY POINT
# ---------------------------

if not st.session_state.logged_in: login_screen()
else: logout_button(); main_app()

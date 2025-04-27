import streamlit as st
import requests
import json
from bs4 import BeautifulSoup

# -----------------------------------
# CONFIGURATION
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

PRODUCT_TYPES = [
    "Casual Pret", "Luxury Pret", "Formal", "Bridal", "Festive",
    "Luxury Lawn", "Summer Lawn", "Winter Collection", "Eid Collection",
    "Chiffon", "Silk", "Party Wear"
]

# -----------------------------------
# LOGIN SYSTEM
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
# SCRAPE FUNCTIONS
# -----------------------------------

def scrape_collection(url):
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, verify=False)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    domain = url.split('/')[2]
    links = soup.select("a[href*='/products/']")
    return list({f"https://{domain}{link['href'].split('?')[0]}" for link in links})

def scrape_product(url):
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, verify=False)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    script = soup.find("script", type="application/ld+json")
    data = json.loads(script.string) if script else {}

    title = data.get("name", "No Title")
    description = data.get("description", "")
    images = data.get("image", [])
    images = images if isinstance(images, list) else [images]

    handle = url.split("/products/")[-1].split("?")[0]
    domain = url.split('/')[2]
    variant_res = requests.get(f"https://{domain}/products/{handle}.js", verify=False).json()

    variants = [{
        "size": v["public_title"] or v["title"],
        "price": str(float(v["price"]) / 100),
        "compareAtPrice": str(float(v["compare_at_price"]) / 100) if v.get("compare_at_price") else None,
        "sku": v.get("sku", "")
    } for v in variant_res.get("variants", [])]

    images_data = [{
        "originalSource": img,
        "altText": f"{title} image {idx + 1}",
        "mediaContentType": "IMAGE"
    } for idx, img in enumerate(images)]

    return {
        "handle": handle, "title": title, "body_html": description,
        "vendor": domain.split('.')[0].capitalize(),
        "variants": variants, "images": images_data
    }

# -----------------------------------
# FETCH SHOPIFY DATA
# -----------------------------------

def fetch_collections_and_tags():
    query = """
    {
      collections(first: 100) {
        edges {
          node { id title ruleSet { rules { column } } }
        }
      }
      shop { productTags(first: 250) { edges { node } } }
    }"""
    res = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": query}, verify=False).json()
    collections = [c["node"] for c in res["data"]["collections"]["edges"] if not c["node"]["ruleSet"]]
    tags = sorted([t["node"] for t in res["data"]["shop"]["productTags"]["edges"]])
    return collections, tags

# -----------------------------------
# SHOPIFY UPLOAD FUNCTIONS
# -----------------------------------

def create_shopify_product(data, product_type, tags):
    query = """
    mutation productSet($product: ProductSetInput!) {
      productSet(input: $product) {
        product { id variants(first:10){edges{node{id inventoryItem{id}}}} }
        userErrors { field message }
      }
    }"""
    product_input = {
        "title": data["title"], "handle": data["handle"],
        "descriptionHtml": data["body_html"], "vendor": data["vendor"],
        "productType": product_type, "tags": tags,
        "productOptions": [{"name": "Size", "position": 1, "values": [{"name": v["size"]} for v in data["variants"]]}],
        "variants": [{"price": v["price"], "optionValues": [{"optionName": "Size", "name": v["size"]}], "sku": v["sku"], "compareAtPrice": v["compareAtPrice"]} for v in data["variants"]]
    }
    res = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": query, "variables": {"product": product_input}}, verify=False).json()
    return res

# -----------------------------------
# STREAMLIT MAIN APP
# -----------------------------------

def main_app():
    st.title("🚀 Shopify Uploader")
    url = st.text_input("Enter Product or Collection URL:")
    collections, tags = fetch_collections_and_tags()

    selected_collections = st.multiselect("Collections:", [c["title"] for c in collections])
    selected_tags = st.multiselect("Tags:", tags)
    product_type = st.selectbox("Product Type:", PRODUCT_TYPES)

    if st.button("Upload"):
        urls = [url] if "/products/" in url else scrape_collection(url)
        for product_url in urls:
            product = scrape_product(product_url)
            response = create_shopify_product(product, product_type, selected_tags)
            if "errors" in response or response["data"]["productSet"]["userErrors"]:
                st.error(f"Error: {response}")
                continue
            st.success(f"{product['title']} uploaded successfully!")

# -----------------------------------
# ENTRY POINT
# -----------------------------------

def run():
    if not st.session_state.logged_in:
        login_screen()
    else:
        logout_button()
        main_app()

if __name__ == "__main__":
    run()

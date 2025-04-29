import streamlit as st
import requests
import json
import openai
from bs4 import BeautifulSoup

# -----------------------------------
# 1. CONFIGURATION
# -----------------------------------

VALID_USERNAME = "admin"
VALID_PASSWORD = "abc123"
SHOP_NAME = "kinzav2.myshopify.com"
API_VERSION = "2025-01"
ACCESS_TOKEN = st.secrets["SHOPIFY_ACCESS_TOKEN"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
openai.api_key = OPENAI_API_KEY

LOCATION_ID = "gid://shopify/Location/91287421246"
PRODUCT_CATEGORY_ID = "gid://shopify/TaxonomyCategory/aa-1-4"
DEFAULT_STOCK = 8
FAQ_PAGE_GLOBAL_ID = "gid://shopify/OnlineStorePage/687485878651"
WE_CARE_PAGE_GLOBAL_ID = "gid://shopify/OnlineStorePage/127953174846"
DISCLAIMER_PAGE_GLOBAL_ID = "gid://shopify/OnlineStorePage/127935152446"
GRAPHQL_ENDPOINT = f"https://{SHOP_NAME}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}

# -----------------------------------
# 2. LOGIN HANDLING
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
            st.error("Invalid credentials")

def logout_button():
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.experimental_rerun()

# -----------------------------------
# 3. SCRAPING FUNCTIONS
# -----------------------------------

def scrape_collection(url):
    res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, verify=False)
    soup = BeautifulSoup(res.text, "html.parser")
    domain = url.split('/')[2]
    product_urls = set(
        f"https://{domain}{a['href'].split('?')[0]}"
        for a in soup.find_all('a', href=True)
        if "/products/" in a['href']
    )
    return list(product_urls)

def scrape_product(url):
    res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, verify=False)
    soup = BeautifulSoup(res.text, "html.parser")
    ld = soup.find("script", type="application/ld+json")
    data = json.loads(ld.string) if ld else {}

    title = data.get("name", "No Title")
    description = data.get("description", "")
    images = data.get("image", [])
    if isinstance(images, str):
        images = [images]
    images = images[:10]

    handle = url.split("/products/")[-1].split("?")[0]
    vendor = url.split('/')[2].split('.')[0].capitalize()

    variants = []
    try:
        var_json = requests.get(f"https://{url.split('/')[2]}/products/{handle}.js", verify=False).json()
        for v in var_json.get("variants", []):
            variants.append({
                "size": v.get("public_title") or "Default",
                "price": str(float(v["price"]) / 100),
                "compareAtPrice": str(float(v["compare_at_price"]) / 100) if v.get("compare_at_price") else None,
                "sku": v.get("sku","")
            })
    except:
        pass

    images_clean = [{"originalSource": img, "altText": f"{title} image {i+1}", "mediaContentType": "IMAGE"} for i, img in enumerate(images)]

    return {"handle": handle, "title": title, "body_html": description, "vendor": vendor, "variants": variants, "images": images_clean}

# -----------------------------------
# 4. GPT ENHANCEMENT
# -----------------------------------

def enhance_description_with_gpt(product_data):
    prompt = f"Enhance and rewrite this product description professionally:\n\n{product_data['body_html']}"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# -----------------------------------
# 5. SHOPIFY GRAPHQL OPERATIONS
# -----------------------------------

def graphql_mutation(payload):
    return requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False).json()

def create_product(product_data, product_type, tags):
    mutation = """
    mutation productCreate($input: ProductInput!) {
      productCreate(input: $input) {
        product { id variants(first:50) { edges { node { inventoryItem { id }}}}}
        userErrors { message }
      }
    }
    """
    sizes = list({v["size"] for v in product_data["variants"]})
    variables = {"input": {
        "title": product_data["title"],
        "descriptionHtml": product_data["body_html"],
        "vendor": product_data["vendor"],
        "productType": product_type,
        "tags": tags,
        "options": ["Size"],
        "variants": [{"price": v["price"], "sku": v["sku"], "option1": v["size"]} for v in product_data["variants"]],
        "images": product_data["images"]
    }}
    resp = graphql_mutation({"query": mutation, "variables": variables})
    return resp

# (Other GraphQL functions omitted for brevity but follow your original logic.)

# -----------------------------------
# 6. MAIN STREAMLIT APP
# -----------------------------------

def main_app():
    st.title("🚀 Shopify Product Uploader")

    product_type = st.selectbox("Product Type", ["Casual Pret", "Luxury Pret", "Formal", "Festive"])
    url = st.text_input("Product or Collection URL")
    tags = st.text_input("Tags (comma separated)").split(",")

    if st.button("Upload"):
        if "/products/" in url:
            urls = [url]
        else:
            urls = scrape_collection(url)

        for product_url in urls:
            product = scrape_product(product_url)
            product["body_html"] = enhance_description_with_gpt(product)
            response = create_product(product, product_type, tags)
            if "errors" in response or response.get("data", {}).get("productCreate", {}).get("userErrors"):
                st.error(f"Error uploading: {product['title']}")
            else:
                st.success(f"Uploaded: {product['title']}")

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

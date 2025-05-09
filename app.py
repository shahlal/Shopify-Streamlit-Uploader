import streamlit as st
import requests
import json
from bs4 import BeautifulSoup
import openai
import math

openai.api_key = st.secrets["OPENAI_API_KEY"]
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# -----------------------------------
# 1. CONFIGURATION
# -----------------------------------

VALID_USERNAME    = "admin"
VALID_PASSWORD    = "shop1"
SHOP_NAME         = "kinzav2.myshopify.com"

# Use a valid Shopify Admin API version (e.g. "2023-10" or "2024-01"):
API_VERSION       = "2025-01"


ACCESS_TOKEN = st.secrets["SHOPIFY_ACCESS_TOKEN"]


LOCATION_ID         = "gid://shopify/Location/91287421246"
PRODUCT_CATEGORY_ID = "gid://shopify/TaxonomyCategory/aa-1-4"
DEFAULT_STOCK       = 8

# Hard-coded FAQ page reference
FAQ_PAGE_GLOBAL_ID = "gid://shopify/OnlineStorePage/687485878651"

# Hard-coded We Care and Disclaimer pages
WE_CARE_PAGE_GLOBAL_ID = "gid://shopify/OnlineStorePage/127953174846"
DISCLAIMER_PAGE_GLOBAL_ID = "gid://shopify/OnlineStorePage/127935152446"

GRAPHQL_ENDPOINT  = f"https://{SHOP_NAME}/admin/api/{API_VERSION}/graphql.json"
HEADERS           = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}


# -----------------------------------
# 2. LOGIN
# -----------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def login_screen():
    st.title("🔒 Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        if u == VALID_USERNAME and p == VALID_PASSWORD:
            st.session_state.logged_in = True
            st.experimental_rerun()
        else:
            st.error("Invalid credentials")

def logout_button():
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.experimental_rerun()

# -----------------------------------
# 3. SCRAPING COLLECTION / PRODUCT
# -----------------------------------

def scrape_collection(url):
    st.info(f"Scraping collection: {url}")
    res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, verify=False)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    domain = url.split('/')[2]
    product_urls = []
    for a in soup.find_all('a', href=True):
        if "/products/" in a['href']:
            link = f"https://{domain}{a['href'].split('?')[0]}"
            if link not in product_urls:
                product_urls.append(link)
    st.success(f"Found {len(product_urls)} products.")
    return product_urls






def scrape_product(url):
    st.info(f"Scraping product: {url}")
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, verify=False)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    # ─── 1. THEME JSON PARSING ───────────────────────────────────────────────────
    product_data = {}
    model_tag = soup.find(
        "script",
        {"type": "application/json",
         "id":   lambda x: x and x.startswith("ModelJson-template")}
    )
    if model_tag and model_tag.string:
        try:
            loaded = json.loads(model_tag.string)
            if isinstance(loaded, list) and loaded:
                product_data = loaded[0]
            elif isinstance(loaded, dict):
                product_data = loaded
        except Exception:
            product_data = {}

    if not product_data:
        # Fallback to LD+JSON
        ld = soup.find("script", type="application/ld+json")
        try:
            product_data = json.loads(ld.string) if ld and ld.string else {}
        except Exception:
            product_data = {}

    title       = product_data.get("name", "No Title")
    description = product_data.get("description", "")
    handle      = url.split("/products/")[-1].split("?")[0]
    vendor      = url.split('/')[2].split('.')[0].capitalize()

    # ─── 2. IMAGE EXTRACTION ──────────────────────────────────────────────────────
    # 2a) Try the proper 'images' array first
    raw_images = product_data.get("images") or []

    # 2b) If that isn't a list, normalise singular 'image' entry
    if not isinstance(raw_images, list):
        raw_images = []
        single = product_data.get("image")
        if isinstance(single, str):
            raw_images = [single]
        elif isinstance(single, dict) and single.get("src"):
            raw_images = [single["src"]]

    # 2c) If still empty, fall back to the Flickity carousel in the HTML
    if not raw_images:
        for img in soup.select("img.photoswipe__image"):
            src = img.get("data-photoswipe-src") or img.get("src")
            if not src:
                continue
            if src.startswith("//"):
                src = "https:" + src
            raw_images.append(src)

    # 2d) Trim down to your usual maximum
    images = raw_images[:10]

    # ─── 3. VARIANTS VIA .js ENDPOINT ────────────────────────────────────────────
    variants = []
    try:
        domain   = url.split('/')[2]
        vres     = requests.get(
            f"https://{domain}/products/{handle}.js",
            headers={"User-Agent": "Mozilla/5.0"}, verify=False
        )
        var_json = vres.json()
        for v in var_json.get("variants", []):
            size_label     = v.get("public_title") or v.get("title") or "Default"
            original_price = float(v["price"]) / 100
            adjusted_price = dynamic_pricing(original_price)
            compare_at     = (f"{float(v['compare_at_price'])/100:.2f}"
                               if v.get("compare_at_price") else None)

            variants.append({
                "size":           size_label,
                "price":          f"{adjusted_price:.2f}",
                "compareAtPrice": compare_at,
                "sku":            v.get("sku", "")
            })
    except Exception:
        st.warning("Failed to fetch variant info")

    return {
        "handle":          handle,
        "title":           f"{vendor} | {title}",
        "raw_description": description,
        "vendor":          vendor,
        "variants":        variants,
        "images":          images
    }

    # ─── 3. VARIANTS VIA .js ENDPOINT (unchanged) ─────────────────────────────
    variants = []
    try:
        domain   = url.split('/')[2]
        vres     = requests.get(
            f"https://{domain}/products/{handle}.js",
            headers={"User-Agent": "Mozilla/5.0"}, verify=False
        )
        var_json = vres.json()
        for v in var_json.get("variants", []):
            size_label     = v.get("public_title") or v.get("title") or "Default"
            original_price = float(v["price"]) / 100
            adjusted_price = dynamic_pricing(original_price)
            compare_at     = (f"{float(v['compare_at_price'])/100:.2f}"
                               if v.get("compare_at_price") else None)

            variants.append({
                "size":           size_label,
                "price":          f"{adjusted_price:.2f}",
                "compareAtPrice": compare_at,
                "sku":            v.get("sku", "")
            })
    except Exception:
        st.warning("Failed to fetch variant info")


    return {
        "handle":          handle,
        "title":           f"{vendor} | {title}",
        "raw_description": description,
        "vendor":          vendor,
        "variants":        variants,
        "images":          images
    }

# -----------------------------------
# 4. FETCH COLLECTIONS & TAGS
# -----------------------------------

def fetch_collections_and_tags():
    query = """
    {
      collections(first:100) {
        edges {
          node {
            id
            title
            ruleSet {
              rules {
                column
              }
            }
          }
        }
      }
      shop {
        productTags(first:250) {
          edges {
            node
          }
        }
      }
    }
    """
    resp = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query":query}, verify=False).json()
    if "data" not in resp:
        st.error(f"Error fetching collections/tags: {resp}")
        return [], []
    
    cols = resp["data"]["collections"]["edges"]
    # A "manual" collection has no rules
    manual = [c for c in cols if not (c["node"].get("ruleSet") or {}).get("rules")]

    tag_edges = resp["data"]["shop"]["productTags"]["edges"]
    tag_list  = sorted(t["node"] for t in tag_edges)
    return manual, tag_list

# -----------------------------------
# 4b. FETCH & FILTER PAGES (GRAPHQL)
# -----------------------------------

def fetch_and_filter_pages():
    """
    Fetch up to 50 pages using GraphQL.
    Return two lists:
      1) delivery_pages -> pages whose title starts with 'Delivery'
      2) size_pages -> pages whose title contains 'size'
    """
    query = """
    {
      pages(first:50) {
        edges {
          node {
            id
            title
          }
        }
      }
    }
    """
    resp = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query":query}, verify=False).json()
    if "data" not in resp or "pages" not in resp["data"]:
        st.error("Unable to fetch pages. Ensure read_content scope is granted.")
        return [], []

    edges = resp["data"]["pages"]["edges"]
    all_pages = [{"id": p["node"]["id"], "title": p["node"]["title"]} for p in edges]

    # Filter for pages whose title starts with "Delivery"
    delivery_pages = [p for p in all_pages if p["title"].lower().startswith("delivery")]
    # Filter for pages containing "size"
    size_chart_pages = [p for p in all_pages if "size" in p["title"].lower()]

    return delivery_pages, size_chart_pages

# -----------------------------------
# 5. CREATE PRODUCT WITH VARIANTS
# -----------------------------------

def create_product_with_variants(product_data):
    mutation = """
    mutation productSet($product: ProductSetInput!) {
      productSet(input: $product) {
        product {
          id
          variants(first:50) {
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
        "title":             product_data["title"],
        "handle":            product_data["handle"],
        "descriptionHtml":   product_data.get("enhanced_description", product_data["raw_description"]),  # ✅ Use GPT-enhanced description if available
        "vendor":            product_data["vendor"],
        "productType":       product_data["productType"],
        "tags":              product_data.get("tags", []),
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

    payload = {"query": mutation, "variables": {"product": product_input}}
    response = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=payload, verify=False).json()

    product_set = response.get("data", {}).get("productSet", {})
    errors      = product_set.get("userErrors", [])
    product_obj = product_set.get("product")

    if errors:
        st.error(f"Create product errors: {errors}")
        return None, []

    if not product_obj or not product_obj.get("id"):
        st.error("No product returned from API.")
        return None, []

    product_id = product_obj["id"]
    inv_ids = [edge["node"]["inventoryItem"]["id"] for edge in product_obj["variants"]["edges"]]
    return product_id, inv_ids


# -----------------------------------
# 6. COMMON GRAPHQL + METAFIELD UPDATES
# -----------------------------------

def graphql_mutation(input_payload):
    return requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json=input_payload, verify=False).json()

def update_product_category(product_id):
    mutation = """
    mutation($i: ProductUpdateInput!) {
      productUpdate(product: $i) {
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {"i": {"id": product_id, "category": PRODUCT_CATEGORY_ID}}
    graphql_mutation({"query": mutation, "variables": variables})

def enable_inventory_tracking(inventory_item_ids):
    mutation = """
    mutation($id: ID!, $input: InventoryItemInput!) {
      inventoryItemUpdate(id: $id, input: $input) {
        userErrors { field message }
      }
    }
    """
    for i in inventory_item_ids:
        graphql_mutation({
            "query": mutation,
            "variables": {"id": i, "input": {"tracked": True}}
        })

def activate_inventory(inventory_item_ids):
    mutation = """
    mutation($iid: ID!, $lid: ID!) {
      inventoryActivate(inventoryItemId:$iid, locationId:$lid) {
        userErrors { field message }
      }
    }
    """
    for i in inventory_item_ids:
        graphql_mutation({
            "query": mutation,
            "variables": {"iid": i, "lid": LOCATION_ID}
        })

def set_inventory_quantity(inventory_item_ids):
    mutation = """
    mutation($input: InventorySetQuantitiesInput!) {
      inventorySetQuantities(input: $input) {
        userErrors { field message }
      }
    }
    """
    changes = [
        {"inventoryItemId": i, "locationId": LOCATION_ID, "quantity": DEFAULT_STOCK}
        for i in inventory_item_ids
    ]
    input_data = {
        "name": "available",
        "reason": "correction",
        "ignoreCompareQuantity": True,
        "quantities": changes
    }
    graphql_mutation({"query": mutation, "variables": {"input": input_data}})

def upload_media(product_id, product_data):
    mutation = """
    mutation($pid: ID!, $med: [CreateMediaInput!]!) {
      productCreateMedia(productId: $pid, media: $med) {
        userErrors {
          field
          message
        }
      }
    }
    """
    media_list = []
    for img in product_data["images"]:
        media_list.append({
            "originalSource": img["originalSource"],
            "mediaContentType": img["mediaContentType"],
            "alt": img.get("altText", "")
        })
    if media_list:
        graphql_mutation({"query": mutation, "variables": {"pid": product_id, "med": media_list}})

# Hardcoded FAQ page:
def update_faqs_metafield(product_id):
    mutation = """
    mutation($i: ProductUpdateInput!) {
      productUpdate(product: $i) {
        userErrors { field message }
      }
    }
    """
    vars = {
        "i": {
            "id": product_id,
            "metafields": [
                {
                    "namespace": "custom",
                    "key": "faqs",
                    "type": "page_reference",
                    "value": FAQ_PAGE_GLOBAL_ID
                }
            ]
        }
    }
    graphql_mutation({"query": mutation, "variables": vars})

# Hard-code We Care + Disclaimer:
def update_we_care_and_disclaimer(product_id):
    """
    Hard-coded:
      custom.we_care_for_you => gid://shopify/OnlineStorePage/127953174846
      custom.disclaimer      => gid://shopify/OnlineStorePage/127935152446
    """
    mutation = """
    mutation($i: ProductUpdateInput!) {
      productUpdate(product: $i) {
        userErrors { field message }
      }
    }
    """
    metafields_list = [
        {
            "namespace": "custom",
            "key": "we_care_for_you",
            "type": "page_reference",
            "value": WE_CARE_PAGE_GLOBAL_ID
        },
        {
            "namespace": "custom",
            "key": "disclaimer",
            "type": "page_reference",
            "value": DISCLAIMER_PAGE_GLOBAL_ID
        }
    ]

    variables = {
        "i": {
            "id": product_id,
            "metafields": metafields_list
        }
    }
    resp = graphql_mutation({"query": mutation, "variables": variables})
    user_errors = resp.get("data",{}).get("productUpdate",{}).get("userErrors",[])
    if user_errors:
        st.warning(f"We Care + Disclaimer Metafield Error: {user_errors}")

# Delivery Time + a separate size chart key
def update_delivery_and_size_chart_metafields(product_id, d_id, s_id):
    """
    If a user picks a 'Delivery...' page => custom.delivery_time
    If a user picks a 'size' page => custom.suffuse_casual_pret_size_chart
    """
    mutation = """
    mutation($i: ProductUpdateInput!) {
      productUpdate(product: $i) {
        userErrors { field message }
      }
    }
    """
    metafields_list = []
    if d_id:
        metafields_list.append({
            "namespace": "custom",
            "key": "delivery_time",
            "type": "page_reference",
            "value": d_id
        })
    if s_id:
        metafields_list.append({
            "namespace": "custom",
            "key": "suffuse_casual_pret_size_chart",
            "type": "page_reference",
            "value": s_id
        })

    if not metafields_list:
        return

    variables = {
        "i": {
            "id": product_id,
            "metafields": metafields_list
        }
    }
    resp = graphql_mutation({"query": mutation, "variables": variables})
    user_errors = resp.get("data",{}).get("productUpdate",{}).get("userErrors",[])
    if user_errors:
        st.warning(f"Delivery/Size Chart Metafields Error: {user_errors}")

def get_publication_ids():
    query = """
    {
      publications(first:20) {
        edges {
          node {
            id
          }
        }
      }
    }
    """
    resp = graphql_mutation({"query": query})
    edges = resp.get("data",{}).get("publications",{}).get("edges",[])
    return [e["node"]["id"] for e in edges]

def publish_product(product_id, publication_ids):
    mutation = """
    mutation($i: ProductPublishInput!) {
      productPublish(input: $i) {
        userErrors { field message }
      }
    }
    """
    product_pubs = [{"publicationId": pid} for pid in publication_ids]
    variables = {"i": {"id": product_id, "productPublications": product_pubs}}
    graphql_mutation({"query": mutation, "variables": variables})

def add_product_to_collections(product_id, coll_ids):
    mutation = """
    mutation($id: ID!, $p: [ID!]!) {
      collectionAddProducts(id: $id, productIds: $p) {
        userErrors { field message }
      }
    }
    """
    for cid in coll_ids:
        graphql_mutation({"query": mutation, "variables": {"id": cid, "p": [product_id]}})

# -----------------------------------
# 7. MAIN APP
# -----------------------------------

def fetch_sitemap(sitemap_url):
    res = requests.get(sitemap_url)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "xml")
    urls = [loc.text for loc in soup.find_all('loc')]
    return urls

def filter_urls(urls):
    collections = [u for u in urls if "/collections/" in u]
    products = [u for u in urls if "/products/" in u]
    return collections, products

@st.cache_data(ttl=3600)
def get_navigation_links():
    sitemap_urls = fetch_sitemap('https://signaturelabels.co.uk/sitemap_collections_1.xml?from=459453825342&to=670428496251')
    collections, products = filter_urls(sitemap_urls)
    return collections, products





from openai import OpenAI
import streamlit as st

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def enhance_description_via_gpt(raw_description, product_title, vendor, product_type, categories, related_products, collection, collection_urls, product_urls):

    shop_by_designer_link = next(
        (u for u in collection_urls if vendor.lower() in u.lower()), '/collections/all'
    )

    category_links = [
        next((u for u in collection_urls if cat.lower().replace(' ', '-') in u.lower()), '/collections/all')
        for cat in categories
    ]

    related_product_links = [
        next((u for u in product_urls if rp.lower().replace(' ', '-') in u.lower()), '/collections/all')
        for rp in related_products
    ]

    prompt = f"""
    You are a professional fashion content writer for "Signature Labels". Write a structured Shopify product description entirely in HTML format.

    Important Instructions:
    - Do NOT include Markdown code blocks at the start or end.
    - Output ONLY HTML directly, ready for Shopify.

    <!-- Product Description -->
    <p>[Detailed introduction about {product_title} by {vendor}. Include collection, fabric details, embroidery, and style specifics.]</p>

    <!-- Product Specifications -->
    <ul>
        <li><strong>Outfit Type:</strong> Eastern Wear</li>
        <li><strong>Collection:</strong> <a href="{shop_by_designer_link}">{collection}</a></li>
        <li><strong>Brand:</strong> {vendor}</li>
        <li><strong>Style:</strong> [Style details]</li>
        <li><strong>Fabric:</strong> [Fabric details]</li>
        <li><strong>Work Technique:</strong> [Techniques]</li>
        <li><strong>Occasion:</strong> {product_type}, Casual Wear, Party Wear, Eid Outfits</li>
        <li><strong>Package Includes:</strong> [Components]</li>
    </ul>

    <!-- Note and Navigation -->
    <p><strong>Note:</strong> Colours may vary slightly due to lighting or screen resolution.</p>
    <p>
        <strong>Shop by Designer:</strong> <a href="{shop_by_designer_link}">{vendor}</a><br>
        <strong>Shop by Categories:</strong> {', '.join(f'<a href="{link}">{cat}</a>' for cat, link in zip(categories, category_links))}<br>
        <strong>Related Products:</strong> {', '.join(f'<a href="{link}">{rp}</a>' for rp, link in zip(related_products, related_product_links))}
    </p>

    <!-- Why It Stands Out -->
    <h3>Why "{product_title}" Stands Out</h3>
    <ul>
        <li>[Key feature 1]</li>
        <li>[Key feature 2]</li>
    </ul>

    <!-- Key Benefits -->
    <h3>Key Benefits</h3>
    <ul>
        <li>[Benefit 1]</li>
        <li>[Benefit 2]</li>
    </ul>

    <!-- About {vendor} -->
    <section id="about-designer">
        <h2>About {vendor}</h2>
        <p>[Designer description]</p>
    </section>
    """

    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        temperature=0.7,
    )

    response_text = completion.choices[0].message.content.strip()

    return response_text



def main_app():
    st.title("🚀 Shopify Uploader")

    # -----------------------------------
    # Product Type selector
    # -----------------------------------
    TYPES = [
        "Casual Pret", "Luxury Pret", "Formal", "Bridal", "Festive",
        "Luxury Lawn", "Summer Lawn", "Winter Collection", "Eid Collection",
        "Chiffon", "Silk", "Party Wear"
    ]
    sel_type = st.selectbox("Select Product Type:", TYPES)

    # -----------------------------------
    # NEW: File uploader for batch URLs
    # -----------------------------------
    uploaded_file = st.file_uploader(
        "Upload a file (txt or csv) with one URL per line",
        type=["txt", "csv"]
    )

    # Only show manual URL input if no file provided
    if not uploaded_file:
        url = st.text_input("Enter Product or Collection URL:")
        urls_to_process = [url.strip()] if url else []
    else:
        if uploaded_file.name.lower().endswith(".csv"):
            import pandas as pd
            df = pd.read_csv(uploaded_file, header=None)
            urls_to_process = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
        else:
            content = uploaded_file.read().decode("utf-8")
            urls_to_process = [
                line.strip() for line in content.splitlines() if line.strip()
            ]

    # -----------------------------------
    # Fetch Shopify collections, tags and pages
    # -----------------------------------
    collections, tags = fetch_collections_and_tags()
    delivery_pages, size_pages = fetch_and_filter_pages()

    coll_dict = {c["node"]["title"]: c["node"]["id"] for c in collections}
    sel_coll = st.multiselect("Select Collections:", list(coll_dict.keys()))
    sel_tags = st.multiselect("Select Tags:", tags)

    del_dict = {p["title"]: p["id"] for p in delivery_pages}
    siz_dict = {p["title"]: p["id"] for p in size_pages}

    del_choice = st.selectbox("Select Delivery Page:", ["-- None --"] + list(del_dict.keys()))
    siz_choice = st.selectbox("Select Size Chart Page:", ["-- None --"] + list(siz_dict.keys()))

    # -----------------------------------
    # Additional metadata inputs
    # -----------------------------------
    categories_input = st.text_input("Categories (comma-separated):", "Luxury Pret, Festive")
    related_products_input = st.text_input(
        "Related Products (comma-separated):",
        "Ivory Embroidered Shirt Set, Pastel Embroidered Kurta Set"
    )
    collection = st.text_input("Collection Name:", "Eid Collection")

    # -----------------------------------
    # Run upload
    # -----------------------------------
    if st.button("Run Upload"):
        if not urls_to_process:
            st.warning("Please enter a URL or upload a file.")
            return

        # Convert selections into IDs
        coll_ids = [coll_dict[name] for name in sel_coll]
        del_id   = del_dict.get(del_choice) if del_choice != "-- None --" else None
        siz_id   = siz_dict.get(siz_choice) if siz_choice != "-- None --" else None

        # Fetch navigation URLs once
        collection_urls, product_urls = get_navigation_links()

        def process_one(product_url):
            p_data = scrape_product(product_url)

            # GPT-enhanced description
            category_list = [c.strip() for c in categories_input.split(",") if c.strip()]
            related_list  = [r.strip() for r in related_products_input.split(",") if r.strip()]

            p_data["enhanced_description"] = enhance_description_via_gpt(
                raw_description   = p_data["raw_description"],
                product_title     = p_data["title"],
                vendor            = p_data["vendor"],
                product_type      = sel_type,
                categories        = category_list,
                related_products  = related_list,
                collection        = collection,
                collection_urls   = collection_urls,
                product_urls      = product_urls
            )

            # Assign type and tags
            p_data["productType"] = sel_type
            p_data["tags"]        = sel_tags

            # Create product & variants
            product_id, inv_ids = create_product_with_variants(p_data)
            if not product_id:
                return

            # Metafields & inventory
            update_product_category(product_id)
            update_faqs_metafield(product_id)
            update_we_care_and_disclaimer(product_id)
            update_delivery_and_size_chart_metafields(product_id, del_id, siz_id)

            enable_inventory_tracking(inv_ids)
            activate_inventory(inv_ids)
            set_inventory_quantity(inv_ids)
            upload_media(product_id, p_data)

            # Publish & add to collections
            publication_ids = get_publication_ids()
            publish_product(product_id, publication_ids)
            add_product_to_collections(product_id, coll_ids)

            st.success(f"Uploaded: {p_data['title']}")

        # Loop through each URL (product or collection)
        for u in urls_to_process:
            if "/products/" in u:
                st.info(f"Single Product Mode: {u}")
                process_one(u)
            else:
                st.info(f"Collection Mode: {u}")
                for p_url in scrape_collection(u):
                    process_one(p_url)

# -----------------------------------
# 8. ENTRY POINT
# -----------------------------------

def run():
    if not st.session_state.logged_in:
        login_screen()
    else:
        logout_button()
        main_app()

if __name__ == "__main__":
    run()

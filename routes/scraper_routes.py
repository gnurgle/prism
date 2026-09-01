import os

import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

from urllib.parse import urlparse

from datetime import date

from bs4 import BeautifulSoup

from PIL import Image

import io



# Primary scraper engine for Cloudflare / WAF bypass

try:

    import cloudscraper

    HAS_CLOUDSCRAPER = True

except ImportError:

    HAS_CLOUDSCRAPER = False



# Backup scraper engine for TLS socket-level impersonation

try:

    from curl_cffi import requests as curl_requests

    HAS_CURL_CFFI = True

except ImportError:

    HAS_CURL_CFFI = False



import requests



scraper_bp = Blueprint('scraper_bp', __name__)



def get_db_from_app():

    from __main__ import get_db

    return get_db()



def clean_filename(name):

    """Sanitize glass name for safe file naming."""

    clean = re.sub(r'[^\w\s-]', '', name or 'glass').strip().lower()

    return re.sub(r'[-\s]+', '_', clean)



def fetch_html_and_image(url):

    """Robust multi-engine fetcher to bypass WAF / Cloudflare 403 blocks."""

    chrome_headers = {

        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",

        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",

        "Accept-Language": "en-US,en;q=0.9",

        "Accept-Encoding": "gzip, deflate, br",

        "Sec-Ch-Ua": '"Chromium";v="128", "Not=A?Brand";v="24", "Google Chrome";v="128"',

        "Sec-Ch-Ua-Mobile": "?0",

        "Sec-Ch-Ua-Platform": '"Windows"',

        "Sec-Fetch-Dest": "document",

        "Sec-Fetch-Mode": "navigate",

        "Sec-Fetch-Site": "cross-site",

        "Sec-Fetch-User": "?1",

        "Upgrade-Insecure-Requests": "1"

    }



    if HAS_CLOUDSCRAPER:

        try:

            scraper = cloudscraper.create_scraper(

                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}

            )

            scraper.headers.update(chrome_headers)

            res = scraper.get(url, timeout=15)

            if res.status_code == 200:

                return res.text, scraper

        except Exception as e:

            print(f"[Scraper Warning] Cloudscraper engine failed: {e}")



    if HAS_CURL_CFFI:

        try:

            s = curl_requests.Session(impersonate="chrome120")

            s.headers.update(chrome_headers)

            res = s.get(url, timeout=15)

            if res.status_code == 200:

                return res.text, s

        except Exception as e:

            print(f"[Scraper Warning] curl_cffi engine failed: {e}")



    s = requests.Session()

    s.headers.update(chrome_headers)

    res = s.get(url, timeout=15)

    res.raise_for_status()

    return res.text, s





def download_raw_image(session, img_url, fallback_prefix):

    """Downloads and caches the raw source image locally during fetch."""

    if not img_url:

        return None

    try:

        if img_url.startswith('//'):

            img_url = 'https:' + img_url

            

        img_resp = session.get(img_url, timeout=10)

        if img_resp.status_code != 200:

            print(f"[Image Error] Failed to download from {img_url} (HTTP Status: {img_resp.status_code})")

            return None



        img_bytes = img_resp.content if hasattr(img_resp, 'content') else img_resp.read()

        upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'glass')

        os.makedirs(upload_folder, exist_ok=True)

        

        filename = f"temp_{fallback_prefix}_{abs(hash(img_url))}.jpg"

        file_path = os.path.join(upload_folder, filename)

        

        with open(file_path, 'wb') as f:

            f.write(img_bytes)

            

        return f"images/glass/{filename}"

    except Exception as e:

        print(f"[Raw Image Download Exception] {e}")

        return None





def process_local_crop(raw_img_path, crop_margin, offset_x, offset_y, glass_id, glass_name):

    """Crops and saves the final glass image locally using the cached raw file."""

    if not raw_img_path:

        return None

    try:

        full_raw_path = os.path.join(current_app.root_path, 'static', raw_img_path)

        if not os.path.exists(full_raw_path):

            print(f"[Crop Error] Cached raw image not found at {full_raw_path}")

            return None



        img = Image.open(full_raw_path).convert("RGB")

        width, height = img.size

        

        left = max(0, min(crop_margin + offset_x, width - 10))

        top = max(0, min(crop_margin - offset_y, height - 10))

        right = max(left + 10, min(width - crop_margin + offset_x, width))

        bottom = max(top + 10, min(height - crop_margin - offset_y, height))

        

        img = img.crop((left, top, right, bottom))

        img = img.resize((768, 768), Image.Resampling.LANCZOS)

        

        filename = f"{glass_id}_{clean_filename(glass_name)}.jpg"

        upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'glass')

        file_path = os.path.join(upload_folder, filename)

        

        img.save(file_path, format="JPEG", quality=95)

        return f"images/glass/{filename}"

    except Exception as e:

        print(f"[Local Crop Exception] {e}")

        return None





def scrape_hobby_lobby(url):

    html, session = fetch_html_and_image(url)

    soup = BeautifulSoup(html, 'html.parser')

    

    title_elem = soup.find('meta', property='og:title') or soup.find('h1')

    raw_name = title_elem.get('content', '').strip() if title_elem and title_elem.has_attr('content') else (title_elem.get_text().strip() if title_elem else 'Hobby Lobby Glass')

    clean_name = re.sub(r'stained\s*glass\s*sheet', '', raw_name, flags=re.IGNORECASE).strip(' -–')

    glsname = clean_name if clean_name else raw_name

    

    manf_elem = soup.find(class_=re.compile(r'^productDetails_productDetailsBrand__'))

    glsmanf = manf_elem.get_text().strip() if manf_elem else "Hobby Lobby"

    

    price = None

    price_elem = soup.find(class_=re.compile(r'productPriceSection_price')) or soup.find(class_=re.compile(r'price', re.IGNORECASE))

    if price_elem:

        price_text = price_elem.get_text()

        try:

            clean_text = ''.join(c for c in price_text if c.isdigit() or c == '.')

            if clean_text:

                price = float(clean_text)

        except ValueError:

            price = None

            

    if price is None:

        page_text = soup.get_text()

        price_match = re.search(r'\$\s*([0-9]+\.[0-9]{2})', page_text)

        if price_match:

            try:

                price = float(price_match.group(1))

            except ValueError:

                pass



    glslen, glswid = None, None

    page_text = soup.get_text()

    dim_match = re.search(r'Dimensions:\s*([0-9.]+)\s*(?:["\']|in)?\s*x\s*([0-9.]+)', page_text, re.IGNORECASE)

    if dim_match:

        try:

            glslen = float(dim_match.group(1))

            glswid = float(dim_match.group(2))

        except ValueError:

            pass



    sku_text = ""

    sku_elem = soup.find(class_=re.compile(r'^productDetails_productDetailsMoreSKU__'))

    if sku_elem:

        sku_content = sku_elem.get_text()

        sku_match = re.search(r'(?:SKU|Item)[:\s#]*([0-9A-Za-z\-_]+)', sku_content, re.IGNORECASE)

        if sku_match:

            sku_text = f"SKU: {sku_match.group(1).strip()}"



    if not sku_text:

        sku_match = re.search(r'(?:Item|SKU)\s*#?\s*([0-9]+)', page_text, re.IGNORECASE)

        if sku_match:

            sku_text = f"SKU: {sku_match.group(1).strip()}"



    img_url = None

    picture_elem = soup.find('picture')

    if picture_elem:

        source_elem = picture_elem.find('source')

        img_elem = picture_elem.find('img')

        if source_elem and source_elem.has_attr('srcset'):

            img_url = source_elem['srcset'].split(',')[0].strip().split(' ')[0]

        elif img_elem and img_elem.has_attr('src'):

            img_url = img_elem['src']

            

    if not img_url:

        og_img = soup.find('meta', property='og:image')

        if og_img and og_img.has_attr('content'):

            img_url = og_img['content']



    raw_img_path = download_raw_image(session, img_url, "hl")



    return {

        "glsname": glsname[:25] if glsname else "",

        "glsmanf": glsmanf[:25] if glsmanf else "Hobby Lobby",

        "glsource": "Hobby Lobby",

        "gllink": url,

        "glsprice": price,

        "glslen": glslen,

        "glswid": glswid,

        "glsthk": 3,

        "gtrnsn": "Translucent",

        "glsimg": raw_img_path,

        "raw_img_path": raw_img_path,

        "glsnote": sku_text,

    }





def scrape_oceanside_glass(url):

    html, session = fetch_html_and_image(url)

    soup = BeautifulSoup(html, 'html.parser')

    

    title_elem = soup.find('h1', class_=re.compile(r'product__title')) or soup.find('meta', property='og:title')

    raw_name = title_elem.get_text().strip() if title_elem and title_elem.name == 'h1' else (title_elem.get('content', '').strip() if title_elem else 'Oceanside Glass')

    glsname = raw_name

    glsmanf = "Oceanside"

    

    price = None

    price_elem = soup.find(class_=re.compile(r'price', re.IGNORECASE))

    if price_elem:

        price_text = price_elem.get_text()

        try:

            clean_text = ''.join(c for c in price_text if c.isdigit() or c == '.')

            if clean_text:

                price = float(clean_text)

        except ValueError:

            price = None

            

    if price is None:

        page_text = soup.get_text()

        price_match = re.search(r'\$\s*([0-9]+\.[0-9]{2})', page_text)

        if price_match:

            try:

                price = float(price_match.group(1))

            except ValueError:

                pass



    gtrnsn = "Translucent"

    page_text = soup.get_text()

    opacity_match = re.search(r'Opacity:\s*([A-Za-z]+)', page_text, re.IGNORECASE)

    if opacity_match:

        gtrnsn = opacity_match.group(1).capitalize()



    glslen, glswid = None, None

    dim_match = re.search(r'(?:Hobby Sheet|Dimensions):\s*([0-9.]+)\s*(?:in|["\'])?\s*x\s*([0-9.]+)', page_text, re.IGNORECASE)

    if dim_match:

        try:

            glslen = float(dim_match.group(1))

            glswid = float(dim_match.group(2))

        except ValueError:

            pass



    sku_text = ""

    sku_match = re.search(r'(?:SKU|Item)[:\s#]*([0-9A-Za-z\-_]+)', page_text, re.IGNORECASE)

    if sku_match:

        sku_text = f"SKU: {sku_match.group(1).strip()}"



    img_url = None

    lightbox_elem = soup.find('a', class_=re.compile(r'lightbox-image'))

    if lightbox_elem and lightbox_elem.has_attr('data-pswp-src'):

        img_url = lightbox_elem['data-pswp-src']

    elif lightbox_elem and lightbox_elem.has_attr('href'):

        img_url = lightbox_elem['href']

    

    if not img_url:

        img_elem = soup.find('img', class_='image__img')

        if img_elem and img_elem.has_attr('src'):

            img_url = img_elem['src']

            

    if not img_url:

        og_img = soup.find('meta', property='og:image')

        if og_img and og_img.has_attr('content'):

            img_url = og_img['content']



    if img_url:

        img_url = re.sub(r'&amp;width=\d+', '', img_url)

        img_url = re.sub(r'\?width=\d+', '', img_url)



    raw_img_path = download_raw_image(session, img_url, "os")



    return {

        "glsname": glsname[:25] if glsname else "",

        "glsmanf": glsmanf[:25] if glsmanf else "Oceanside",

        "glsource": "Glass Ingenuity",

        "gllink": url,

        "glsprice": price,

        "glslen": glslen,

        "glswid": glswid,

        "glsthk": 3,

        "gtrnsn": gtrnsn,

        "glsimg": raw_img_path,

        "raw_img_path": raw_img_path,

        "glsnote": sku_text,

    }





def scrape_wissmach_glass(url):

    html, session = fetch_html_and_image(url)

    soup = BeautifulSoup(html, 'html.parser')

    

    glsname = "Wissmach Glass"

    content_div = soup.find('div', class_='entry-the-content')

    if content_div:

        p_elem = content_div.find('p')

        if p_elem:

            glsname = p_elem.get_text().strip()

            

    if not glsname or glsname == "Wissmach Glass":

        title_elem = soup.find('h1', class_=re.compile(r'entry-title'))

        if title_elem:

            glsname = title_elem.get_text().strip()



    glsmanf = "Wissmach Glass"

    

    price = None

    page_text = soup.get_text()

    price_match = re.search(r'\$\s*([0-9]+\.[0-9]{2})', page_text)

    if price_match:

        try:

            price = float(price_match.group(1))

        except ValueError:

            pass



    glslen, glswid = 12.0, 12.0



    sku_text = ""

    headline_elem = soup.find('h1', class_=re.compile(r'entry-title'))

    if headline_elem:

        sku_text = f"SKU: {headline_elem.get_text().strip()}"



    img_url = None

    img_div = soup.find('div', itemprop='image')

    if img_div:

        meta_url = img_div.find('meta', itemprop='url')

        if meta_url and meta_url.has_attr('content'):

            img_url = meta_url['content']

            

    if not img_url:

        og_img = soup.find('meta', property='og:image')

        if og_img and og_img.has_attr('content'):

            img_url = og_img['content']



    if img_url:

        img_url = re.sub(r'\?fit=\d+%2C\d+&amp;ssl=1', '', img_url)

        img_url = re.sub(r'\?fit=\d+,\d+&ssl=1', '', img_url)



    raw_img_path = download_raw_image(session, img_url, "wiss")



    return {

        "glsname": glsname[:25] if glsname else "",

        "glsmanf": glsmanf[:25] if glsmanf else "Wissmach Glass",

        "glsource": "Glass Ingenuity",

        "gllink": url,

        "glsprice": price,

        "glslen": glslen,

        "glswid": glswid,

        "glsthk": 3,

        "gtrnsn": "Translucent",

        "glsimg": raw_img_path,

        "raw_img_path": raw_img_path,

        "glsnote": sku_text,

    }





@scraper_bp.route('/glass/scrape', methods=['GET', 'POST'])

def scrape_glass_page():

    db = get_db_from_app()

    scraped_data = None

    

    if request.method == 'POST':

        action = request.form.get('action')

        

        if action == 'fetch':

            url = request.form.get('url', '').strip()

            if not url:

                flash("Please provide a valid product URL.", "danger")

            else:

                parsed_url = urlparse(url)

                domain = parsed_url.netloc.lower()

                if domain.startswith('www.'):

                    domain = domain[4:]

                

                try:

                    if 'hobbylobby.com' in domain:

                        scraped_data = scrape_hobby_lobby(url)

                    elif 'oceansideglass.com' in domain:

                        scraped_data = scrape_oceanside_glass(url)

                    elif 'wissmachglass.com' in domain:

                        scraped_data = scrape_wissmach_glass(url)

                    else:

                        flash("Website domain not supported.", "danger")

                    

                    if scraped_data:

                        flash("Page successfully scraped! Review details below.", "success")

                except Exception as e:

                    error_msg = str(e)

                    if "403" in error_msg:

                        flash("403 Blocked: The website firewall blocked automated retrieval. Ensure 'pip install cloudscraper' is installed.", "danger")

                    else:

                        flash(f"Error scraping page: {e}", "danger")

                

        elif action == 'save':

            url = request.form.get('GLLINK', '').strip() or request.form.get('gllink', '').strip()

            

            # Safe integer conversion with fallbacks for empty form inputs

            crop_margin_raw = request.form.get('crop_margin')

            crop_margin = int(crop_margin_raw) if crop_margin_raw and crop_margin_raw.strip() else 50

            

            offset_x_raw = request.form.get('offset_x')

            offset_x = int(offset_x_raw) if offset_x_raw and offset_x_raw.strip() else 0

            

            offset_y_raw = request.form.get('offset_y')

            offset_y = int(offset_y_raw) if offset_y_raw and offset_y_raw.strip() else 0

            

            # Look for GLSIMG, glsimg, or raw_img_path interchangeably

            raw_img_path = (

                request.form.get('GLSIMG') or 

                request.form.get('glsimg') or 

                request.form.get('raw_img_path', '')

            ).strip()
            

            # Look for GLSIMG, glsimg, or raw_img_path interchangeably

            raw_img_path = (

                request.form.get('GLSIMG') or 

                request.form.get('glsimg') or 

                request.form.get('raw_img_path', '')

            ).strip()

            

            glsname = request.form.get('GLSNAME') or request.form.get('glsname')

            glsmanf = request.form.get('GLSMANF') or request.form.get('glsmanf')

            glstex = request.form.get('GLSTEX') or request.form.get('glstex') or None

            gtrnsn = request.form.get('GTRNSN') or request.form.get('gtrnsn') or None

            color = request.form.get('COLOR') or request.form.get('color') or None

            

            parsed_url = urlparse(url)

            domain = parsed_url.netloc.lower()

            if domain.startswith('www.'):

                domain = domain[4:]

            

            glsource = "Hobby Lobby" if 'hobbylobby.com' in domain else "Glass Ingenuity"

                

            glslen = request.form.get('GLSLEN') or request.form.get('glslen') or None

            glswid = request.form.get('GLSWID') or request.form.get('glswid') or None

            glsthk = request.form.get('GLSTHK') or request.form.get('glsthk') or None

            glsiri = 1 if (request.form.get('GLSIRI') or request.form.get('glsiri')) else 0

            glsopal = 1 if (request.form.get('GLSOPAL') or request.form.get('glsopal')) else 0

            gllink = url or None

            glsnote = request.form.get('GLSNOTE') or request.form.get('glsnote')

            price = request.form.get('GLSPRICE') or request.form.get('glsprice')

            isactive = 1



            try:

                cursor = db.execute(

                    """

                    INSERT INTO GSI (GLSNAME, GLSMANF, GLSTEX, GTRNSN, COLOR, GLSOURCE, 

                        GLSLEN, GLSWID, GLSTHK, GLSIRI, GLSOPAL, GLLINK, 

                        GLSIMG, GLSNOTE, ISACTIVE)

                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)

                    """,

                    (glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen,

                     glswid, glsthk, glsiri, glsopal, gllink, None, glsnote, isactive),

                )

                glass_id = cursor.lastrowid



                glsimg = None

                if raw_img_path:

                    try:

                        glsimg = process_local_crop(raw_img_path, crop_margin, offset_x, offset_y, glass_id, glsname)

                        if glsimg:

                            db.execute("UPDATE GSI SET GLSIMG = ? WHERE GLASSID = ?", (glsimg, glass_id))

                    except Exception as e:

                        print(f"Local crop processing error: {e}")



                if price:

                    db.execute(

                        "INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, ?)",

                        (glass_id, price, date.today().isoformat()),

                    )



                db.commit()

                flash("Glass sheet recorded successfully!", "success")

                return redirect(url_for("glass_bp.list_glass"))

                

            except Exception as e:

                db.rollback()

                print(f"[Database Save Exception] {e}")

                flash(f"Database Error: {e}", "danger")



    textures = db.execute("SELECT * FROM GTL").fetchall()

    colors = db.execute("SELECT * FROM COLOR").fetchall()

    sources = db.execute("SELECT * FROM GSL").fetchall()

    transparency = db.execute("SELECT * FROM GTRNS").fetchall()

    

    return render_template(

        "glass_scraper.html",

        textures=textures,

        colors=colors,

        sources=sources,

        transparency=transparency,

        glass=scraped_data,

        scraped_url=request.form.get('url', '') if request.method == 'POST' else ''

    )

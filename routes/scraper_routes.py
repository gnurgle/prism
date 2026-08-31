import os

import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

from urllib.parse import urlparse

from datetime import date

import requests

from bs4 import BeautifulSoup

from PIL import Image

import io



scraper_bp = Blueprint('scraper_bp', __name__)



def get_db_from_app():

    from __main__ import get_db

    return get_db()



def scrape_hobby_lobby(url, crop_margin=50, offset_x=0, offset_y=0, apply_crop=False):

    """

    Refined scraper for Hobby Lobby stained glass product pages.

    Saves the raw uncropped image. Only applies the crop/resize transformation when apply_crop=True (on final save).

    """

    headers = {

        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    }

    response = requests.get(url, headers=headers, timeout=15)

    response.raise_for_status()

    

    soup = BeautifulSoup(response.text, 'html.parser')

    

    # Extract Glass Name and strip "Stained Glass Sheet"

    title_elem = soup.find('meta', property='og:title') or soup.find('h1')

    raw_name = title_elem.get('content', '').strip() if title_elem and title_elem.has_attr('content') else (title_elem.get_text().strip() if title_elem else 'Hobby Lobby Glass')

    

    clean_name = re.sub(r'stained\s*glass\s*sheet', '', raw_name, flags=re.IGNORECASE).strip(' -–')

    glsname = clean_name if clean_name else raw_name

    

    # Extract Manufacturer using partial class matching

    manf_elem = soup.find(class_=re.compile(r'^productDetails_productDetailsBrand__'))

    glsmanf = manf_elem.get_text().strip() if manf_elem else "Hobby Lobby"

    

    # Extract Price using robust class matching / regex selectors

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



    # Extract Dimensions matching pattern like: Dimensions: 12" x 12"

    glslen, glswid = None, None

    page_text = soup.get_text()

    dim_match = re.search(r'Dimensions:\s*([0-9.]+)\s*(?:["\']|in)?\s*x\s*([0-9.]+)', page_text, re.IGNORECASE)

    if dim_match:

        try:

            glslen = float(dim_match.group(1))

            glswid = float(dim_match.group(2))

        except ValueError:

            pass



    # Extract SKU for Notes

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



    # Extract Image URL

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



    image_path = None

    if img_url:

        try:

            if img_url.startswith('//'):

                img_url = 'https:' + img_url

            img_resp = requests.get(img_url, headers=headers, timeout=10)

            if img_resp.status_code == 200:

                img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")

                width, height = img.size

                

                upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'glass')

                os.makedirs(upload_folder, exist_ok=True)

                

                if apply_crop:

                    left = crop_margin + offset_x

                    top = crop_margin - offset_y

                    right = width - crop_margin + offset_x

                    bottom = height - crop_margin - offset_y

                    

                    left = max(0, min(left, width - 10))

                    top = max(0, min(top, height - 10))

                    right = max(left + 10, min(right, width))

                    bottom = max(top + 10, min(bottom, height))

                    

                    img = img.crop((left, top, right, bottom))

                    img = img.resize((768, 768), Image.Resampling.LANCZOS)

                    

                    filename = f"hl_{abs(hash(url))}.jpg"

                else:

                    filename = f"hl_raw_{abs(hash(url))}.jpg"

                    

                file_path = os.path.join(upload_folder, filename)

                img.save(file_path, format="JPEG", quality=95)

                image_path = f"images/glass/{filename}"

        except Exception as e:

            print(f"Image processing error: {e}")



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

        "glsimg": image_path,

        "glsnote": sku_text,

        "crop_margin": crop_margin,

        "offset_x": offset_x,

        "offset_y": offset_y

    }



@scraper_bp.route('/glass/scrape', methods=['GET', 'POST'])

def scrape_glass_page():

    db = get_db_from_app()

    scraped_data = None

    

    if request.method == 'POST':

        action = request.form.get('action')

        

        if action == 'fetch':

            url = request.form.get('url', '').strip()

            crop_margin = int(request.form.get('crop_margin', 50))

            offset_x = int(request.form.get('offset_x', 0))

            offset_y = int(request.form.get('offset_y', 0))

            

            if not url:

                flash("Please provide a valid product URL.", "danger")

            else:

                # Dynamically parse domain from the URL

                parsed_url = urlparse(url)

                domain = parsed_url.netloc.lower()

                if domain.startswith('www.'):

                    domain = domain[4:]

                

                if 'hobbylobby.com' in domain:

                    try:

                        scraped_data = scrape_hobby_lobby(url, crop_margin, offset_x, offset_y, apply_crop=False)

                        flash("Page successfully scraped! Review and adjust details below.", "success")

                    except Exception as e:

                        flash(f"Error scraping page: {e}", "danger")

                else:

                    flash("Website not supported", "danger")

                

        elif action == 'save':

            url = request.form.get('GLLINK', '').strip()

            crop_margin = int(request.form.get('crop_margin', 50))

            offset_x = int(request.form.get('offset_x', 0))

            offset_y = int(request.form.get('offset_y', 0))

            

            glsimg = None

            if url:

                try:

                    final_data = scrape_hobby_lobby(url, crop_margin, offset_x, offset_y, apply_crop=True)

                    glsimg = final_data.get('glsimg')

                except Exception as e:

                    print(f"Final crop processing error: {e}")



            glsname = request.form.get('GLSNAME')

            glsmanf = request.form.get('GLSMANF')

            glstex = request.form.get('GLSTEX') or None

            gtrnsn = request.form.get('GTRNSN') or None

            color = request.form.get('COLOR') or None

            glsource = "Hobby Lobby"

            glslen = request.form.get('GLSLEN') or None

            glswid = request.form.get('GLSWID') or None

            glsthk = request.form.get('GLSTHK') or None

            glsiri = 1 if request.form.get('GLSIRI') else 0

            glsopal = 1 if request.form.get('GLSOPAL') else 0

            gllink = url or None

            glsnote = request.form.get('GLSNOTE')

            price = request.form.get('GLSPRICE')

            isactive = 1



            cursor = db.execute(

                """

                INSERT INTO GSI (GLSNAME, GLSMANF, GLSTEX, GTRNSN, COLOR, GLSOURCE, 

                    GLSLEN, GLSWID, GLSTHK, GLSIRI, GLSOPAL, GLLINK, 

                    GLSIMG, GLSNOTE, ISACTIVE)

                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)

                """,

                (glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen,

                 glswid, glsthk, glsiri, glsopal, gllink, glsimg, glsnote, isactive),

            )

            glass_id = cursor.lastrowid



            if price:

                db.execute(

                    "INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, '2020-01-01')",

                    (glass_id, price),

                )



            db.commit()

            flash("Glass sheet recorded successfully from scraper!", "success")

            return redirect(url_for("glass_bp.list_glass"))



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

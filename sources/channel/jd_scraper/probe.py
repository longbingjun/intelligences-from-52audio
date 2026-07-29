"""Browser-based JD SKU price probe (warm navigation path)."""







from __future__ import annotations







from datetime import datetime, timezone



from urllib.parse import quote







from sources.channel.jd_scraper.extractors import (



    best_price,



    classify_page,



    extract_dom_prices,



    fetch_p3_price,



    fetch_ware_business,



)



from sources.channel.jd_scraper.session import human_delay











def open_item_page(page, sku: str, keyword: str | None = None) -> None:



    """Warm path: home -> optional search -> item (reduces bot signals vs direct deep link)."""



    page.goto("https://www.jd.com/", wait_until="domcontentloaded", timeout=45000)



    human_delay()



    if keyword:



        search_url = f"https://search.jd.com/Search?keyword={quote(keyword)}&enc=utf-8"



        page.goto(search_url, wait_until="domcontentloaded", timeout=45000, referer="https://www.jd.com/")



        human_delay()



        link = page.locator(f'a[href*="{sku}"]').first



        if link.count():



            link.click(timeout=10000)



            page.wait_for_load_state("domcontentloaded", timeout=45000)



            page.wait_for_timeout(2000)



            return



    url = f"https://item.jd.com/{sku}.html"



    page.goto(url, wait_until="domcontentloaded", timeout=45000, referer="https://www.jd.com/")



    page.wait_for_timeout(2500)











def probe_sku(



    context,



    target: dict,



    *,



    keyword: str | None = None,



    wait_for_login: bool = False,



) -> dict:



    sku = target["sku_id"]



    url = f"https://item.jd.com/{sku}.html"



    page = context.new_page()



    result = {



        "label": target.get("label", sku),



        "sku_id": sku,



        "url": url,



        "final_url": "",



        "title": "",



        "page_flags": [],



        "dom": {},



        "p3_api": {},



        "ware_business": {},



        "price_cny": None,



        "msrp_cny": None,



        "price_source": None,



        "status": "fail",



        "probed_at": datetime.now(timezone.utc).isoformat(),



    }



    try:



        open_item_page(page, sku, keyword=keyword or target.get("keyword"))



        if wait_for_login and "passport.jd.com" in page.url:



            print(



                "\n京东当前要求登录。请在打开的 Chrome 窗口中完成登录，"



                "确认登录成功后回到此终端按 Enter 继续..."



            )



            input()



            # 登录成功后京东通常会自行跳回原商品页；不要同时强制

            # 导航到首页，否则会与京东的自动跳转产生导航竞争。

            page.wait_for_timeout(3000)

            if "item.jd.com" not in page.url:

                open_item_page(page, sku, keyword=keyword or target.get("keyword"))



        result["final_url"] = page.url



        result["title"] = page.title() or ""



        body_snip = ""



        try:



            body_snip = page.locator("body").inner_text(timeout=5000)[:2000]



        except Exception:



            pass



        result["page_flags"] = classify_page(page.url, result["title"], body_snip)



        result["dom"] = extract_dom_prices(page)



        result["p3_api"] = fetch_p3_price(page, sku)



        result["ware_business"] = fetch_ware_business(page, sku)



        price, msrp, source = best_price(result["dom"], result["p3_api"], result["ware_business"])



        result["price_cny"] = price



        result["msrp_cny"] = msrp



        result["price_source"] = source



        if "freq403" in result["page_flags"]:



            result["status"] = "freq403"



        elif "soft_block" in result["page_flags"]:



            result["status"] = "soft_block"



        elif price is not None:



            result["status"] = "ok"



        elif "login_redirect" in result["page_flags"] or "login_wall" in result["page_flags"]:



            result["status"] = "login_required"



        else:



            result["status"] = "no_price"



    except Exception as exc:



        result["status"] = "error"



        result["error"] = str(exc)



    finally:



        page.close()



    return result




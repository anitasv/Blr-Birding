import urllib.request
import urllib.parse
import json
import time

def fetch_wiki_details_with_redirect(title):
    encoded_title = urllib.parse.quote(title)
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={encoded_title}&redirects=1&prop=pageimages|info&inprop=url&piprop=thumbnail&pithumbsize=800&format=json"
    
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    continue
                fullurl = page_data.get("fullurl")
                thumbnail = page_data.get("thumbnail", {}).get("source")
                return {
                    "title": page_data.get("title"),
                    "page_url": fullurl,
                    "image_url": thumbnail
                }
    except Exception as e:
        print(f"Error fetching {title}: {e}")
    return None

if __name__ == "__main__":
    queries = [
        "Malabar Trogon",
        "Sri Lanka Frogmouth",
        "Malabar Whistling Thrush",
        "King Cobra",
        "Lion-tailed Macaque",
        "Malabar Giant Squirrel",
        "Agumbe"
    ]
    for q in queries:
        res = fetch_wiki_details_with_redirect(q)
        if res:
            print(f"Query: {q} -> Real Title: {res['title']}")
            print(f"  URL: {res['page_url']}")
            print(f"  Img: {res['image_url']}")
        else:
            print(f"Not found: {q}")
        time.sleep(1.5)


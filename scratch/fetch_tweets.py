import urllib.request, json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

urls = [
    'https://twitter.com/neerajjj6785/status/2104895659157684597',
    'https://twitter.com/pritipatelor/status/2104788896915857666',
    'https://twitter.com/itsPaulAi/status/2105037960525852865'
]

for url in urls:
    try:
        req = urllib.request.Request(f'https://publish.twitter.com/oembed?url={url}')
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            print(f"\n--- TWEET BY {data.get('author_name')} ---")
            html = data.get('html', '')
            text = re.sub(r'<[^>]+>', '', html).replace('&mdash;', '-').replace('&amp;', '&').replace('&gt;', '>')
            print(text.strip())
    except Exception as e:
        print(f"Error fetching {url}: {e}")

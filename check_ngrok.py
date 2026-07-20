import urllib.request, json
try:
    req = urllib.request.Request('http://127.0.0.1:4040/api/requests/http')
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())
        for r in data.get('requests', []):
            print(f"Method: {r['request']['method']} Path: {r['request']['uri']} Status: {r['response']['status_code']}")
except Exception as e:
    print(e)

import os
import urllib.request
import json

def main():
    target_dir = r"C:\Users\qiwai\models\kokoro"
    os.makedirs(target_dir, exist_ok=True)
    
    # Get latest release from github API
    api_url = "https://api.github.com/repos/thewh1teagle/kokoro-onnx/releases"
    print("Fetching releases from GitHub...")
    req = urllib.request.Request(api_url)
    # add dummy user-agent to prevent 403
    req.add_header('User-Agent', 'Mozilla/5.0')
    
    with urllib.request.urlopen(req) as response:
        releases = json.loads(response.read().decode())
        
    # We want to find kokoro-v1.1-zh.onnx and voices-v1.1-zh.bin across any recent releases
    # Usually they are attached to a recent release
    wanted = ["kokoro-v1.1-zh.onnx", "voices-v1.1-zh.bin"]
    downloaded = set()
    
    for release in releases:
        for asset in release.get("assets", []):
            name = asset["name"]
            if name in wanted and name not in downloaded:
                url = asset["browser_download_url"]
                dest = os.path.join(target_dir, name)
                print(f"Downloading {name} from {url} ...")
                urllib.request.urlretrieve(url, dest)
                print(f"Saved {name} to {dest}")
                downloaded.add(name)
        if len(downloaded) == len(wanted):
            break
            
    if len(downloaded) < len(wanted):
        print("Could not find all required assets in the releases!")
    else:
        print("Success!")

if __name__ == "__main__":
    main()

import onlinesequencer_engine as oe

ok = oe._start_chrome()
ws = oe._get_ws_url()

# Navigate to a specific sequence page and look for download URL
seq_id = "5728319"
oe._cdp_navigate(ws, f"https://onlinesequencer.net/{seq_id}", wait_cf=5.0)

# Get the page title and look for MIDI download links
find_midi_js = """
(() => {
    const info = {
        title: document.title,
        links: []
    };
    // Find all links that might relate to MIDI download
    document.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        if (href.includes('midi') || href.includes('.mid') || href.includes('download') || href.includes('export')) {
            info.links.push({href, text: a.textContent.trim().substring(0, 50)});
        }
    });
    // Also look for buttons or elements with download/midi text
    document.querySelectorAll('button, [onclick], [data-action]').forEach(el => {
        const txt = el.textContent.trim();
        const onclick = el.getAttribute('onclick') || '';
        if (txt.toLowerCase().includes('midi') || txt.toLowerCase().includes('download') || onclick.includes('midi')) {
            info.links.push({tag: el.tagName, text: txt.substring(0, 80), onclick: onclick.substring(0, 100)});
        }
    });
    // Network requests - check page source for midi URL patterns
    const html = document.documentElement.outerHTML;
    const midiUrls = [];
    const re = /['"]((?:https?:\/\/[^'"]*)?(?:midi|\.mid)[^'"]*)['"]/gi;
    let m;
    while ((m = re.exec(html)) !== null && midiUrls.length < 10) {
        midiUrls.push(m[1]);
    }
    info.midiUrls = midiUrls;
    return JSON.stringify(info);
})()
"""
import json
result = oe._cdp_eval(ws, find_midi_js, timeout=10.0)
if result:
    data = json.loads(result)
    print("Page title:", data.get('title'))
    print("\nMIDI-related links:")
    for l in data.get('links', []):
        print(" ", l)
    print("\nMIDI URL patterns found in HTML:")
    for u in data.get('midiUrls', []):
        print(" ", u)

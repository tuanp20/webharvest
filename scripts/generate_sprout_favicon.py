import os
import tempfile
from PIL import Image
from playwright.sync_api import sync_playwright

def generate_sprout_image(output_path, size=512):
    svg_content = f"""<!DOCTYPE html>
<html>
<head>
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100%;
    width: 100%;
    overflow: hidden;
  }}
  svg {{
    width: 90%;
    height: 90%;
  }}
</style>
</head>
<body>
<svg
  xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 24 24"
  fill="none"
  stroke="#5e5ce6"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
>
  <path d="M14 9.536V7a4 4 0 0 1 4-4h1.5a.5.5 0 0 1 .5.5V5a4 4 0 0 1-4 4 4 4 0 0 0-4 4c0 2 1 3 1 5a5 5 0 0 1-1 3" />
  <path d="M4 9a5 5 0 0 1 8 4 5 5 0 0 1-8-4" />
  <path d="M5 21h14" />
</svg>
</body>
</html>
"""

    with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
        f.write(svg_content)
        temp_html_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": size, "height": size})
            page.goto(f"file:///{temp_html_path}")
            # wait a bit for rendering
            page.wait_for_timeout(500)
            page.screenshot(path=output_path, omit_background=True)
            browser.close()
        print(f"Generated base icon using Playwright at: {output_path}")
    finally:
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_icon_path = os.path.join(base_dir, 'logo_assets', 'logo_icon.png')
    
    # Ensure logo_assets directory exists
    os.makedirs(os.path.dirname(logo_icon_path), exist_ok=True)
    
    # 1. Generate the base 512x512 sprout image with transparent background
    generate_sprout_image(logo_icon_path, size=512)
    
    # Open the generated image for resizing
    img = Image.open(logo_icon_path)
    
    # Target directories to save the favicons
    targets = [
        os.path.join(base_dir, 'license_server', 'static'),
        os.path.join(base_dir, 'license_server', 'static', 'admin'),
        os.path.join(base_dir, 'webharvest', 'static')
    ]
    
    for target in targets:
        os.makedirs(target, exist_ok=True)
        print(f"Saving favicons to target: {target}")
        
        # 1. favicon.ico (16x16, 32x32, 48x48)
        ico_path = os.path.join(target, 'favicon.ico')
        img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
        print(f"  Saved favicon.ico -> {ico_path}")
        
        # 2. favicon-32x32.png
        png32_path = os.path.join(target, 'favicon-32x32.png')
        png32 = img.resize((32, 32), Image.Resampling.LANCZOS)
        png32.save(png32_path, 'PNG')
        print(f"  Saved favicon-32x32.png -> {png32_path}")
        
        # 3. favicon-16x16.png
        png16_path = os.path.join(target, 'favicon-16x16.png')
        png16 = img.resize((16, 16), Image.Resampling.LANCZOS)
        png16.save(png16_path, 'PNG')
        print(f"  Saved favicon-16x16.png -> {png16_path}")
        
        # 4. apple-touch-icon.png (180x180)
        apple_path = os.path.join(target, 'apple-touch-icon.png')
        apple_img = img.resize((180, 180), Image.Resampling.LANCZOS)
        apple_img.save(apple_path, 'PNG')
        print(f"  Saved apple-touch-icon.png -> {apple_path}")
        
    print("All sprout favicons generated and saved successfully!")

if __name__ == '__main__':
    main()

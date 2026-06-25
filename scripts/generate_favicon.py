import os
import shutil
from PIL import Image

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_assets_dir = os.path.join(base_dir, 'logo_assets')
    logo_path = os.path.join(logo_assets_dir, 'logo_square.png')
    desktop_png_path = os.path.join(logo_assets_dir, 'desktop_icon.png')
    desktop_ico_path = os.path.join(logo_assets_dir, 'desktop_icon.ico')
    
    if not os.path.exists(logo_path):
        print(f"Error: Logo file not found at {logo_path}")
        return
        
    print(f"Opening logo image from {logo_path}...")
    img = Image.open(logo_path)
    
    # 600x600 centered crop: (left, top, right, bottom)
    left = 212
    top = 140
    right = 812
    bottom = 740
    
    print(f"Cropping image to ({left}, {top}, {right}, {bottom})...")
    cropped = img.crop((left, top, right, bottom))
    
    # Save the high-res crop to logo_assets/logo_icon.png
    high_res_crop_path = os.path.join(logo_assets_dir, 'logo_icon.png')
    logo_icon_512 = cropped.resize((512, 512), Image.Resampling.LANCZOS)
    logo_icon_512.save(high_res_crop_path, 'PNG')
    print(f"Saved high-res icon to {high_res_crop_path}")
    
    # Process Desktop Icons
    if os.path.exists(desktop_png_path):
        print(f"Opening desktop icon from {desktop_png_path}...")
        desktop_img = Image.open(desktop_png_path)
        
        # Save as icon.icns (macOS)
        icns_path = os.path.join(logo_assets_dir, 'icon.icns')
        desktop_img.save(icns_path, format='ICNS')
        print(f"Saved icon.icns -> {icns_path}")
        
        # Copy desktop_icon.png to icon.png
        shutil.copy2(desktop_png_path, os.path.join(logo_assets_dir, 'icon.png'))
        print("Copied desktop_icon.png -> icon.png")
        
        # Generate WebHarvest.iconset folder assets
        iconset_dir = os.path.join(logo_assets_dir, 'WebHarvest.iconset')
        if os.path.exists(iconset_dir):
            sizes = {
                'icon_16x16.png': (16, 16),
                'icon_16x16@2x.png': (32, 32),
                'icon_32x32.png': (32, 32),
                'icon_32x32@2x.png': (64, 64),
                'icon_128x128.png': (128, 128),
                'icon_128x128@2x.png': (256, 256),
                'icon_256x256.png': (256, 256),
                'icon_256x256@2x.png': (512, 512),
                'icon_512x512.png': (512, 512),
                'icon_512x512@2x.png': (1024, 1024)
            }
            for filename, size in sizes.items():
                dest_path = os.path.join(iconset_dir, filename)
                resized = desktop_img.resize(size, Image.Resampling.LANCZOS)
                resized.save(dest_path, 'PNG')
                print(f"  Generated iconset asset {filename} -> {dest_path}")
                
    if os.path.exists(desktop_ico_path):
        # Copy desktop_icon.ico to icon.ico
        shutil.copy2(desktop_ico_path, os.path.join(logo_assets_dir, 'icon.ico'))
        print("Copied desktop_icon.ico -> icon.ico")

    # Target directories
    targets = [
        os.path.join(base_dir, 'license_server', 'static'),
        os.path.join(base_dir, 'license_server', 'static', 'admin'),
        os.path.join(base_dir, 'webharvest', 'static')
    ]
    
    for target in targets:
        os.makedirs(target, exist_ok=True)
        print(f"Generating favicons in target: {target}")
        
        # 1. favicon.ico (16x16, 32x32, 48x48)
        ico_path = os.path.join(target, 'favicon.ico')
        cropped.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
        print(f"  Generated favicon.ico -> {ico_path}")
        
        # 2. favicon-32x32.png
        png32_path = os.path.join(target, 'favicon-32x32.png')
        png32 = cropped.resize((32, 32), Image.Resampling.LANCZOS)
        png32.save(png32_path, 'PNG')
        print(f"  Generated favicon-32x32.png -> {png32_path}")
        
        # 3. favicon-16x16.png
        png16_path = os.path.join(target, 'favicon-16x16.png')
        png16 = cropped.resize((16, 16), Image.Resampling.LANCZOS)
        png16.save(png16_path, 'PNG')
        print(f"  Generated favicon-16x16.png -> {png16_path}")
        
        # 4. apple-touch-icon.png (180x180)
        apple_path = os.path.join(target, 'apple-touch-icon.png')
        apple_img = cropped.resize((180, 180), Image.Resampling.LANCZOS)
        apple_img.save(apple_path, 'PNG')
        print(f"  Generated apple-touch-icon.png -> {apple_path}")

        # 5. logo_icon.png (512x512)
        logo_icon_path = os.path.join(target, 'logo_icon.png')
        logo_icon_img = cropped.resize((512, 512), Image.Resampling.LANCZOS)
        logo_icon_img.save(logo_icon_path, 'PNG')
        print(f"  Generated logo_icon.png -> {logo_icon_path}")

        # 6. Desktop icon fallbacks in static folder
        if os.path.exists(desktop_png_path):
            shutil.copy2(os.path.join(logo_assets_dir, 'icon.png'), os.path.join(target, 'icon.png'))
            shutil.copy2(os.path.join(logo_assets_dir, 'icon.icns'), os.path.join(target, 'icon.icns'))
        if os.path.exists(desktop_ico_path):
            shutil.copy2(os.path.join(logo_assets_dir, 'icon.ico'), os.path.join(target, 'icon.ico'))
            
    print("Favicon generation completed successfully!")

if __name__ == '__main__':
    main()

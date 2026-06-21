import os
from PIL import Image

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_path = os.path.join(base_dir, 'logo_assets', 'logo_square.png')
    
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
    high_res_crop_path = os.path.join(base_dir, 'logo_assets', 'logo_icon.png')
    cropped.save(high_res_crop_path, 'PNG')
    print(f"Saved high-res icon to {high_res_crop_path}")
    
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
        
    print("Favicon generation completed successfully!")

if __name__ == '__main__':
    main()

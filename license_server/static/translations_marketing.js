const resources = {
    vi: {
        // Metadata & Navigation
        meta_title: "WebHarvest - Trình cào dữ liệu & tải ảnh tự động chuyên nghiệp",
        meta_description: "Giải pháp cào dữ liệu website và tải ảnh hàng loạt hàng đầu Việt Nam. Tích hợp proxy xoay dân cư DataImpulse, hỗ trợ Google Sheets, Excel và bypass Cloudflare.",
        nav_features: "Tính năng",
        nav_simulator: "Chạy thử",
        nav_comparison: "Bảng So Sánh",
        nav_pricing: "Bảng giá",
        nav_download: "Tải Setup",

        // Hero Section
        hero_badge: "Trình cào dữ liệu chuyên sâu thế hệ mới",
        hero_title: "Tự động cào thông tin & tải ảnh hàng loạt",
        hero_subtitle: "Giải pháp crawl dữ liệu tối tân hỗ trợ cào danh sách Excel, Google Sheets. Vượt qua cơ chế chống bot Cloudflare, tích hợp Proxy xoay dân cư từ DataImpulse và tự động hoá trích xuất dữ liệu.",
        btn_register_license: "Đăng Ký Bản Quyền",
        btn_download_free: "Tải Bộ Setup Miễn Phí",

        // Interactive Simulator (Playground)
        sim_template_label: "Chọn Website Mẫu",
        sim_option_shopee: "Trang sản phẩm Shopee (Dynamic JS)",
        sim_option_pinterest: "Pinterest Gallery (Stealth Chromium)",
        sim_option_shopify: "Shopify Catalog (Static Parser)",
        sim_url_label: "Đường Dẫn URL Cần Cào",
        sim_fetcher_label: "Chế Độ Fetcher",
        sim_option_auto: "Auto-selection (Khuyên dùng)",
        sim_option_stealth: "Stealth Playwright (Bypass Firewall)",
        sim_option_static: "Static httpx (Tốc độ cao)",
        sim_btn_start: "Bắt Đầu Chạy Thử",
        sim_log_ready: "[System] Sẵn sàng cào. Chọn website mẫu và ấn \"Bắt Đầu Chạy Thử\".",

        // Showcase Section
        showcase_title: "Hỗ trợ phân tích dữ liệu tự động các nền tảng phổ biến",
        showcase_shopee: "Shopee Việt Nam",
        showcase_lazada: "Lazada Mall",
        showcase_pinterest: "Pinterest Gallery",
        showcase_etsy: "Etsy Storefront",
        showcase_shopify: "Shopify System",
        showcase_sheets_excel: "Google Sheets / Excel",

        // Steps Section
        steps_title: "Quy trình hoạt động 3 bước đơn giản",
        steps_subtitle: "Không cần biết lập trình, cào trích xuất hàng triệu dữ liệu chỉ với vài bước trực quan.",
        step1_title: "Tải và Cài Đặt Setup",
        step1_desc: "Tải xuống ứng dụng WebHarvest cho Windows/macOS. Ứng dụng chạy trực tiếp không cần cài đặt Python hay môi trường phức tạp.",
        step2_title: "Cấu Hình Link Hoặc Tệp",
        step2_desc: "Nhập địa chỉ website cần cào hoặc tải lên file Excel/Google Sheets chứa hàng loạt đường dẫn. Chọn định dạng ảnh mong muốn.",
        step3_title: "Nhận Kết Quả Tải Về",
        step3_desc: "Ứng dụng tự động cào, tải ảnh chất lượng cao vào các thư mục riêng biệt, và tạo file Excel chứa thông tin đầy đủ cấu trúc.",

        // Core Features
        features_title: "Tính năng ưu việt, thiết kế tối ưu",
        features_subtitle: "Hệ thống lõi cào dữ liệu tối tân vượt trội hơn mọi giải pháp cào dữ liệu thông thường.",
        feature_cloudflare_title: "Vượt Qua Cloudflare",
        feature_cloudflare_desc: "Bộ cào ẩn danh cao cấp giả lập đầy đủ vân tay trình duyệt, vượt qua các hệ thống phát hiện bot của Cloudflare và chống cào dữ liệu.",
        feature_proxy_title: "Proxy Dân Cư DataImpulse",
        feature_proxy_desc: "Kết nối trực tiếp thông qua bể Proxy xoay dân cư sạch của nhà cung cấp DataImpulse. Địa chỉ IP được thay đổi liên tục.",
        feature_fallback_title: "Tự Động Fallback IP Local",
        feature_fallback_desc: "Trong trường hợp băng thông Proxy hết hạn hoặc lỗi kết nối, hệ thống tự động chuyển sang IP Local để cào dữ liệu không bị ngắt quãng.",
        feature_binding_title: "Device Binding (SHA256)",
        feature_binding_desc: "Quản lý kích hoạt bản quyền an toàn, mã hóa thông tin phần cứng máy tính bằng mã SHA256. Có nút Hủy kích hoạt để đổi máy tự do.",
        feature_dedup_title: "Tự Động Tránh Trùng Lặp",
        feature_dedup_desc: "Kiểm tra trùng lặp thông minh dựa trên tên tệp và hash nội dung. Tiết kiệm băng thông tối đa, không bao giờ tải lại ảnh cũ.",
        feature_speed_title: "Tốc Độ Crawl Siêu Tốc",
        feature_speed_desc: "Công nghệ lập trình bất tuần tự (async/await) giúp cào đồng thời hàng chục luồng dữ liệu, nâng cao năng suất gấp 5 lần.",

        // Comparison Table
        compare_title: "So sánh chi tiết các gói bản quyền",
        compare_subtitle: "Chi tiết các thông số kỹ thuật và hạn mức tài nguyên của từng gói dịch vụ.",
        compare_header_feature: "Tính Năng So Sánh",
        compare_header_basic: "Gói Basic",
        compare_header_pro: "Gói Pro (Khuyên Dùng)",
        compare_header_unlimited: "Gói Unlimited",
        compare_row_urls_limit: "Hạn mức URLs cào / ngày",
        compare_row_threads_limit: "Số luồng cào đồng thời",
        compare_row_proxy_limit: "Dung lượng Proxy DataImpulse / tháng",
        compare_row_static_parser: "Bộ cào Tĩnh (Static Parser)",
        compare_row_dynamic_parser: "Bộ cào Động (Playwright JS)",
        compare_row_stealth_mode: "Bộ cào Ẩn Danh (Stealth Mode)",
        compare_row_batch_scraping: "Cào hàng loạt (Excel/Sheets/CSV)",
        compare_row_device_binding: "Giới hạn thiết bị kích hoạt (Device Binding)",
        compare_row_unbind_button: "Nút Hủy kích hoạt đổi máy tự động",
        compare_row_fallback_ip: "Tự động Fallback IP Local",
        compare_row_tech_support: "Hỗ trợ kỹ thuật",
        compare_val_50_urls: "50 URLs",
        compare_val_500_urls: "500 URLs",
        compare_val_unlimited: "Không giới hạn",
        compare_val_1_thread: "1 luồng",
        compare_val_5_threads: "5 luồng",
        compare_val_20_threads: "20 luồng",
        compare_val_1gb: "1.0 GB",
        compare_val_10gb: "10.0 GB",
        compare_val_50gb: "50.0 GB",
        compare_val_yes_supported: "Có hỗ trợ",
        compare_val_no: "Không",
        compare_val_1_device: "1 thiết bị",
        compare_val_yes_max_2: "Có (Tối đa 2 lần)",
        compare_val_support_email: "Qua Email",
        compare_val_support_zalo: "Ưu tiên qua Zalo/UltraViewer",
        compare_val_support_engineer: "Kỹ sư hỗ trợ 24/7 riêng biệt",

        // Pricing Section
        pricing_title: "Bảng giá gói đăng ký",
        pricing_subtitle: "Chọn gói bản quyền phù hợp để mở khóa sức mạnh cào dữ liệu của bạn.",
        duration_1_month: "1 Tháng",
        duration_3_months: "3 Tháng (-10%)",
        duration_6_months: "6 Tháng (-15%)",
        duration_12_months: "1 Năm (-20%)",
        popular_badge: "PHỔ BIẾN NHẤT",
        plan_basic_title: "⚡ Basic Plan",
        plan_basic_desc: "Dành cho nhu cầu nghiên cứu & cào dữ liệu nhỏ",
        plan_period: "/ chu kỳ",
        plan_feature_urls_50: "50 URLs cào mỗi ngày",
        plan_feature_threads_1: "1 Luồng cào đồng thời",
        plan_feature_static_auto: "Bộ cào Tĩnh & Tự động",
        plan_feature_proxy_1gb: "1 GB Băng thông Proxy DataImpulse",
        plan_feature_batch: "Hỗ trợ cào hàng loạt (Excel/Sheets)",
        plan_feature_stealth: "Bộ cào Ẩn danh (Stealth Playwright)",
        plan_feature_fallback: "Hỗ trợ Fallback IP Local tự động",
        plan_pro_title: "⭐ Pro Plan",
        plan_pro_desc: "Gói phổ biến nhất cho người làm Marketing & MMO",
        plan_feature_urls_500: "500 URLs cào mỗi ngày",
        plan_feature_threads_5: "5 Luồng cào đồng thời",
        plan_feature_all_fetchers: "Tất cả Fetcher (Tĩnh, Động, Ẩn danh)",
        plan_feature_proxy_10gb: "10 GB Băng thông Proxy DataImpulse",
        plan_feature_batch_import: "Nhập tệp Excel/Google Sheets hàng loạt",
        plan_feature_catalog_extract: "Trích xuất cấu trúc Catalog sản phẩm",
        plan_feature_zalo_support: "Hỗ trợ kĩ thuật ưu tiên Zalo",
        plan_unlimited_title: "💎 Unlimited Plan",
        plan_unlimited_desc: "Dành cho các doanh nghiệp, quy mô khai thác lớn",
        plan_feature_urls_unlimited: "Không giới hạn URLs cào hàng ngày",
        plan_feature_threads_20: "20 Luồng cào đồng thời",
        plan_feature_all_premium: "Đầy đủ tính năng cao cấp nhất",
        plan_feature_proxy_50gb: "50 GB Băng thông Proxy DataImpulse",
        plan_feature_batch_unlimited: "Cào hàng loạt không giới hạn tệp",
        plan_feature_auto_classify: "Tự động phân loại dữ liệu theo nhóm",
        plan_feature_support_24_7: "Hỗ trợ riêng biệt UltraViewer 24/7",
        btn_buy_now: "Mua gói ngay",

        // FAQ Section
        faq_title: "Câu hỏi thường gặp (FAQ)",
        faq_subtitle: "Giải đáp các thắc mắc về quá trình sử dụng bản quyền, proxy và cài đặt.",
        faq_q1: "Tôi có thể chuyển đổi License Key sang máy khác sử dụng không?",
        faq_a1: "Có. Trình cào dữ liệu WebHarvest hỗ trợ cơ chế unbinding tự động. Tại giao diện Cài đặt trên ứng dụng Desktop, bạn chỉ cần click nút \"Hủy Kích Hoạt Thiết Bị\". Hệ thống sẽ giải phóng key của bạn khỏi phần cứng máy hiện tại và cho phép bạn kích hoạt trên máy mới (Mỗi Key hỗ trợ unbind tối đa 2 lần trước khi cần admin hỗ trợ reset).",
        faq_q2: "Dung lượng Proxy DataImpulse tính phí thế nào?",
        faq_a2: "Mỗi gói bản quyền được tặng kèm dung lượng băng thông Proxy xoay dân cư tốc độ cao định kỳ hàng tháng (Basic: 1GB, Pro: 10GB, Unlimited: 50GB). Băng thông này chỉ bị trừ khi bạn tiến hành cào dữ liệu qua hệ thống Proxy. Nếu hết băng thông, hệ thống sẽ tự động chuyển sang IP Local (IP nhà của bạn) để đảm bảo không bị dừng chương trình.",
        faq_q3: "Tại sao tôi nên chọn cào bằng Stealth Mode?",
        faq_a3: "Chế độ Stealth Mode khởi chạy trình duyệt Chromium đã được tối ưu hóa đặc biệt nhằm vượt qua các thuật toán chống bot nâng cao (như Cloudflare Challenge, Akamai, Datadome). Khi trang web bạn cào chặn các truy cập thông thường, Stealth Mode kết hợp cùng Proxy xoay dân cư sẽ là giải pháp cào an toàn nhất.",
        faq_q4: "Tôi có nhận được License Key ngay lập tức sau khi thanh toán không?",
        faq_a4: "Có. Ngay khi bạn chuyển khoản thành công bằng mã QR qua cổng PayOS, Webhook của hệ thống sẽ tự động ghi nhận giao dịch, sinh mã License Key và gửi thông báo trực tiếp qua địa chỉ Email bạn đã đăng ký. Đồng thời, trang kết quả thanh toán trên trình duyệt của bạn sẽ tự động hiển thị License Key để bạn sao chép ngay.",

        // Download Section & Checkout Modal
        download_title: "Tải ứng dụng WebHarvest Desktop",
        download_subtitle: "Tương thích hoàn toàn với các hệ điều hành phổ biến nhất. Tải về và chạy ngay.",
        download_win_title: "Windows",
        download_win_desc: "Yêu cầu Windows 10/11 x64",
        btn_download_win: "Tải Setup (.exe)",
        download_mac_title: "macOS",
        download_mac_desc: "Intel & Apple Silicon (M1/M2/M3)",
        btn_download_mac: "Tải Disk Image (.dmg)",
        modal_checkout_title: "Thanh toán",
        modal_checkout_desc: "Nhập thông tin nhận License Key bản quyền",
        form_name_label: "Họ và tên",
        form_name_placeholder: "Nguyễn Văn A",
        form_email_label: "Địa chỉ Email",
        form_email_placeholder: "email@example.com",
        form_email_hint: "* Vui lòng nhập đúng Email để nhận key bản quyền tự động.",
        btn_pay_payos: "Thanh toán qua cổng PayOS",
        footer_copyright: "© 2026 WebHarvest Inc. Bản quyền được bảo lưu.",

        // JS dynamic strings
        js_months: "tháng",
        js_year: "năm",
        js_billing_cycle: "Chu kỳ đăng ký:",
        js_price_equivalent: "Tương đương {price}/tháng",
        js_form_validation: "Vui lòng điền đầy đủ họ tên và email.",
        js_payment_failed: "Tạo link thanh toán thất bại.",
        js_connection_error: "Lỗi kết nối đến server.",
        js_initializing: "Đang khởi tạo thanh toán...",

        // Sim logs
        sim_log_sys_start: "[System] Khởi động trình cào dữ liệu WebHarvest...",
        sim_log_shopee_mode: "[System] Chế độ cào: Dynamic JS Fetcher (Playwright).",
        sim_log_proxy_connect: "[System] Đang kết nối tới Proxy xoay dân cư DataImpulse...",
        sim_log_proxy_ip: "[Proxy] Đã nhận IP: 185.220.101.42 (Hanoi, Vietnam).",
        sim_log_shopee_open: "[Browser] Đang mở trang: https://shopee.vn/product-sample-detail-i.12039.4019",
        sim_log_cloudflare_challenge: "[Cloudflare] Đang vượt qua kiểm tra bảo mật (Bypass Challenge)...",
        sim_log_cloudflare_success: "[Cloudflare] Bypass thành công trong 1.8s.",
        sim_log_lazy_load: "[Browser] Cuộn trang tự động để tải hình ảnh (Lazy Load)...",
        sim_log_shopee_parse_title: "[Parser] Đã trích xuất: Tên sản phẩm: \"Áo khoác gió thời trang\".",
        sim_log_shopee_parse_price: "[Parser] Đã trích xuất: Giá: 299,000đ | Kho hàng: 142.",
        sim_log_shopee_images: "[Parser] Tìm thấy 6 hình ảnh sản phẩm độ phân giải cao.",
        sim_log_download_dir: "[Downloader] Đang tải ảnh xuống thư mục cục bộ...",
        sim_log_download_success_6: "[Downloader] Đã tải thành công 6/6 ảnh.",
        sim_log_export_shopee: "[Exporter] Đã xuất file Excel dữ liệu: /output/shopee_products.xlsx",
        sim_log_sys_success_shopee: "[System] Tiến trình hoàn tất thành công trong 6.4s.",

        sim_log_stealth_mode: "[System] Chế độ cào: Stealth Mode (Bypass bot detection).",
        sim_log_proxy_ip_tokyo: "[Proxy] Kết nối qua Proxy DataImpulse: IP: 93.115.95.12 (Tokyo, Japan).",
        sim_log_pinterest_open: "[Browser] Đang mở URL Pinterest...",
        sim_log_pinterest_success: "[Browser] Trang Pinterest tải thành công.",
        sim_log_pinterest_grid: "[Parser] Tìm kiếm các liên kết hình ảnh gốc trong Gallery Grid...",
        sim_log_pinterest_images: "[Parser] Trích xuất thành công 24 ảnh độ phân giải cao.",
        sim_log_download_parallel_24: "[Downloader] Đang tải song song 24 ảnh...",
        sim_log_download_success_24: "[Downloader] Tải thành công 24 ảnh. (Tốc độ TB: 4.8MB/s).",
        sim_log_sys_success_pinterest: "[System] Cào dữ liệu hoàn tất trong 4.2s.",

        sim_log_static_mode: "[System] Chế độ cào: Static Parser (httpx - Tốc độ cực hạn).",
        sim_log_bypass_proxy: "[System] Bỏ qua Proxy (sử dụng IP Local để tối ưu hóa tốc độ).",
        sim_log_http_get: "[Static] Đang gửi yêu cầu GET HTTP...",
        sim_log_http_200: "[Static] Server phản hồi: 200 OK trong 180ms.",
        sim_log_dom_parse: "[Parser] Phân tích cây DOM HTML...",
        sim_log_shopify_catalog: "[Parser] Tìm thấy cấu trúc Catalog của 50 sản phẩm.",
        sim_log_shopify_extract: "[Parser] Trích xuất thành công: Tên, Giá, SKU, Biến thể và Ảnh.",
        sim_log_export_shopify: "[Exporter] Đã xuất file Excel dữ liệu: /output/shopify_all.xlsx",
        sim_log_sys_success_shopify: "[System] Hoàn tất 50 sản phẩm trong 1.5s."
    },
    en: {
        // Metadata & Navigation
        meta_title: "WebHarvest - Professional Web Scraper & Batch Image Downloader",
        meta_description: "Leading web scraping & batch image downloading solution in Vietnam. Integrated DataImpulse rotating residential proxies, supports Excel/Google Sheets, and bypasses Cloudflare.",
        nav_features: "Features",
        nav_simulator: "Sandbox",
        nav_comparison: "Comparison",
        nav_pricing: "Pricing",
        nav_download: "Download Setup",

        // Hero Section
        hero_badge: "Next-Gen Advanced Web Scraper",
        hero_title: "Automate Data Scraping & Download Images in Bulk",
        hero_subtitle: "State-of-the-art scraping solution supporting Excel lists and Google Sheets. Bypasses Cloudflare firewalls, integrates DataImpulse rotating residential proxies, and automates data extraction.",
        btn_register_license: "Register License Key",
        btn_download_free: "Download Free Setup",

        // Interactive Simulator (Playground)
        sim_template_label: "Select Website Template",
        sim_option_shopee: "Shopee Product Page (Dynamic JS)",
        sim_option_pinterest: "Pinterest Gallery (Stealth Chromium)",
        sim_option_shopify: "Shopify Catalog (Static Parser)",
        sim_url_label: "Target Scrape URL",
        sim_fetcher_label: "Fetcher Mode",
        sim_option_auto: "Auto-selection (Recommended)",
        sim_option_stealth: "Stealth Playwright (Bypass Firewall)",
        sim_option_static: "Static httpx (High Speed)",
        sim_btn_start: "Start Sandbox Run",
        sim_log_ready: "[System] Ready to scrape. Choose a website template and click \"Start Sandbox Run\".",

        // Showcase Section
        showcase_title: "Supports automated data extraction for popular e-commerce platforms",
        showcase_shopee: "Shopee Vietnam",
        showcase_lazada: "Lazada Mall",
        showcase_pinterest: "Pinterest Gallery",
        showcase_etsy: "Etsy Storefront",
        showcase_shopify: "Shopify System",
        showcase_sheets_excel: "Google Sheets / Excel",

        // Steps Section
        steps_title: "Simple 3-Step Process",
        steps_subtitle: "Extract millions of data points in just a few intuitive steps, no programming required.",
        step1_title: "Download & Install Setup",
        step1_desc: "Download the WebHarvest app for Windows/macOS. Runs directly without Python or complex environmental setup.",
        step2_title: "Configure Links or Files",
        step2_desc: "Enter target URLs or upload an Excel/Google Sheets file with batch links. Choose your preferred image formats.",
        step3_title: "Download Scraped Results",
        step3_desc: "The app automatically scrapes data, downloads HD images to dedicated folders, and exports a fully structured Excel file.",

        // Core Features
        features_title: "Powerful Features, Optimized Design",
        features_subtitle: "Advanced core engine that outperforms traditional web scraping tools.",
        feature_cloudflare_title: "Bypass Cloudflare",
        feature_cloudflare_desc: "Premium stealth scraper mimics complete browser fingerprints to bypass Cloudflare anti-bot firewalls and scraping blocks.",
        feature_proxy_title: "DataImpulse Residential Proxy",
        feature_proxy_desc: "Connects directly via DataImpulse's clean residential rotating proxy pool. IP addresses rotate continuously.",
        feature_fallback_title: "Local IP Auto-Fallback",
        feature_fallback_desc: "Automatically falls back to your local IP if proxy bandwidth expires or disconnects, ensuring uninterrupted scraping.",
        feature_binding_title: "Device Binding (SHA256)",
        feature_binding_desc: "Secure license binding using computer hardware hashes encrypted with SHA256. Includes an \"Unbind\" option to change devices freely.",
        feature_dedup_title: "Smart De-duplication",
        feature_dedup_desc: "Smart duplicate detection based on file names and content hashes. Saves bandwidth by never downloading the same image twice.",
        feature_speed_title: "Ultra-Fast Scraping Speed",
        feature_speed_desc: "Asynchronous programming architecture (async/await) runs dozens of concurrent threads, multiplying efficiency by 5x.",

        // Comparison Table
        compare_title: "Detailed Plan Comparison",
        compare_subtitle: "Detailed technical specifications and resource limits for each plan.",
        compare_header_feature: "Feature Comparison",
        compare_header_basic: "Basic Plan",
        compare_header_pro: "Pro Plan (Recommended)",
        compare_header_unlimited: "Unlimited Plan",
        compare_row_urls_limit: "Daily Scraping URL Limit",
        compare_row_threads_limit: "Concurrent Scrape Threads",
        compare_row_proxy_limit: "DataImpulse Proxy Bandwidth / Month",
        compare_row_static_parser: "Static Parser Engine",
        compare_row_dynamic_parser: "Dynamic Parser Engine (Playwright JS)",
        compare_row_stealth_mode: "Stealth Mode (Anti-Detection)",
        compare_row_batch_scraping: "Batch Scraping (Excel/Sheets/CSV)",
        compare_row_device_binding: "Device Binding Activation Limit",
        compare_row_unbind_button: "Auto Device Unbind Button",
        compare_row_fallback_ip: "Local IP Auto-Fallback",
        compare_row_tech_support: "Technical Support",
        compare_val_50_urls: "50 URLs",
        compare_val_500_urls: "500 URLs",
        compare_val_unlimited: "Unlimited",
        compare_val_1_thread: "1 thread",
        compare_val_5_threads: "5 threads",
        compare_val_20_threads: "20 threads",
        compare_val_1gb: "1.0 GB",
        compare_val_10gb: "10.0 GB",
        compare_val_50gb: "50.0 GB",
        compare_val_yes_supported: "Supported",
        compare_val_no: "No",
        compare_val_1_device: "1 device",
        compare_val_yes_max_2: "Yes (Max 2 times)",
        compare_val_support_email: "Via Email",
        compare_val_support_zalo: "Priority Support via Zalo/UltraViewer",
        compare_val_support_engineer: "24/7 Dedicated Support Engineer",

        // Pricing Section
        pricing_title: "Pricing Plans",
        pricing_subtitle: "Choose the right license plan to unlock your web scraping potential.",
        duration_1_month: "1 Month",
        duration_3_months: "3 Months (-10%)",
        duration_6_months: "6 Months (-15%)",
        duration_12_months: "1 Year (-20%)",
        popular_badge: "MOST POPULAR",
        plan_basic_title: "⚡ Basic Plan",
        plan_basic_desc: "For personal research & small-scale scraping",
        plan_period: "/ cycle",
        plan_feature_urls_50: "50 URL scrapes per day",
        plan_feature_threads_1: "1 concurrent scrape thread",
        plan_feature_static_auto: "Static & Auto Scraper Engines",
        plan_feature_proxy_1gb: "1 GB DataImpulse Proxy Bandwidth",
        plan_feature_batch: "Batch Scraping Support (Excel/Sheets)",
        plan_feature_stealth: "Stealth Scraper (Stealth Playwright)",
        plan_feature_fallback: "Auto-fallback to local IP",
        plan_pro_title: "⭐ Pro Plan",
        plan_pro_desc: "Most popular plan for Marketers & MMO players",
        plan_feature_urls_500: "500 URL scrapes per day",
        plan_feature_threads_5: "5 concurrent scrape threads",
        plan_feature_all_fetchers: "All Fetchers (Static, Dynamic, Stealth)",
        plan_feature_proxy_10gb: "10 GB DataImpulse Proxy Bandwidth",
        plan_feature_batch_import: "Bulk import Excel/Google Sheets files",
        plan_feature_catalog_extract: "Product Catalog structure extraction",
        plan_feature_zalo_support: "Zalo Priority Tech Support",
        plan_unlimited_title: "💎 Unlimited Plan",
        plan_unlimited_desc: "For enterprises and large-scale data mining",
        plan_feature_urls_unlimited: "Unlimited daily URL scrapes",
        plan_feature_threads_20: "20 concurrent scrape threads",
        plan_feature_all_premium: "Complete suite of premium features",
        plan_feature_proxy_50gb: "50 GB DataImpulse Proxy Bandwidth",
        plan_feature_batch_unlimited: "Unlimited batch file imports",
        plan_feature_auto_classify: "Automatic data categorization by groups",
        plan_feature_support_24_7: "24/7 Dedicated UltraViewer Support",
        btn_buy_now: "Buy Plan Now",

        // FAQ Section
        faq_title: "Frequently Asked Questions (FAQ)",
        faq_subtitle: "Answers to common questions regarding licensing, proxies, and setups.",
        faq_q1: "Can I transfer my License Key to another computer?",
        faq_a1: "Yes. WebHarvest features an automatic unbinding system. In the Desktop App's Settings, simply click \"Deactivate Device\". This releases your key from the current hardware, letting you activate it on a new machine. (Each Key supports up to 2 self-unbinds before requiring admin assistance).",
        faq_q2: "How is DataImpulse Proxy bandwidth billed?",
        faq_a2: "Each license includes complimentary high-speed rotating residential proxy bandwidth every month (Basic: 1GB, Pro: 10GB, Unlimited: 50GB). Bandwidth is consumed only when scraping through the proxy system. If you run out, it automatically falls back to your local IP to prevent the scraping process from stopping.",
        faq_q3: "Why should I choose Stealth Mode?",
        faq_a3: "Stealth Mode launches a custom-optimized Chromium browser designed to bypass advanced bot detection algorithms (such as Cloudflare Challenge, Akamai, Datadome). When target sites block standard scrapers, Stealth Mode combined with residential proxies offers the safest solution.",
        faq_q4: "Will I receive the License Key instantly after payment?",
        faq_a4: "Yes. Once the payment is successfully completed via PayOS QR code, our Webhook automatically processes the transaction, generates a License Key, and sends it directly to your registered email. The checkout confirmation page on your browser will also display the key for instant copy-pasting.",

        // Download Section & Checkout Modal
        download_title: "Download WebHarvest Desktop App",
        download_subtitle: "Fully compatible with popular operating systems. Download and run instantly.",
        download_win_title: "Windows",
        download_win_desc: "Requires Windows 10/11 x64",
        btn_download_win: "Download Installer (.exe)",
        download_mac_title: "macOS",
        download_mac_desc: "Intel & Apple Silicon (M1/M2/M3)",
        btn_download_mac: "Download Disk Image (.dmg)",
        modal_checkout_title: "Payment Checkout",
        modal_checkout_desc: "Enter details to receive your license key automatically",
        form_name_label: "Full Name",
        form_name_placeholder: "John Doe",
        form_email_label: "Email Address",
        form_email_placeholder: "email@example.com",
        form_email_hint: "* Please enter a valid email to receive your license key automatically.",
        btn_pay_payos: "Pay via PayOS Gateway",
        footer_copyright: "© 2026 WebHarvest Inc. All rights reserved.",

        // JS dynamic strings
        js_months: "months",
        js_year: "year",
        js_billing_cycle: "Billing cycle:",
        js_price_equivalent: "Equivalent to {price}/month",
        js_form_validation: "Please enter your full name and email.",
        js_payment_failed: "Payment link generation failed.",
        js_connection_error: "Connection error.",
        js_initializing: "Initializing payment...",

        // Sim logs
        sim_log_sys_start: "[System] Launching WebHarvest core scraper...",
        sim_log_shopee_mode: "[System] Scraper engine: Dynamic JS Fetcher (Playwright).",
        sim_log_proxy_connect: "[System] Connecting to DataImpulse rotating residential proxy...",
        sim_log_proxy_ip: "[Proxy] Received IP: 185.220.101.42 (Hanoi, Vietnam).",
        sim_log_shopee_open: "[Browser] Opening target URL: https://shopee.vn/product-sample-detail-i.12039.4019",
        sim_log_cloudflare_challenge: "[Cloudflare] Resolving security checks (Bypass Challenge)...",
        sim_log_cloudflare_success: "[Cloudflare] Bypass successful in 1.8s.",
        sim_log_lazy_load: "[Browser] Auto-scrolling page to trigger lazy loading...",
        sim_log_shopee_parse_title: "[Parser] Extracted product name: \"Áo khoác gió thời trang\" (Windbreaker Jacket).",
        sim_log_shopee_parse_price: "[Parser] Extracted pricing: 299,000 VND | Stock: 142.",
        sim_log_shopee_images: "[Parser] Discovered 6 high-definition product images.",
        sim_log_download_dir: "[Downloader] Downloading images to local directory...",
        sim_log_download_success_6: "[Downloader] Successfully downloaded 6/6 images.",
        sim_log_export_shopee: "[Exporter] Exported Excel sheet structure: /output/shopee_products.xlsx",
        sim_log_sys_success_shopee: "[System] Scraping campaign finished successfully in 6.4s.",

        sim_log_stealth_mode: "[System] Scraper engine: Stealth Mode (Bypass bot detection).",
        sim_log_proxy_ip_tokyo: "[Proxy] Route via DataImpulse proxy: IP: 93.115.95.12 (Tokyo, Japan).",
        sim_log_pinterest_open: "[Browser] Navigating to Pinterest board...",
        sim_log_pinterest_success: "[Browser] Pinterest page loaded successfully.",
        sim_log_pinterest_grid: "[Parser] Locating original high-res image sources in grid...",
        sim_log_pinterest_images: "[Parser] Successfully extracted 24 high-res images.",
        sim_log_download_parallel_24: "[Downloader] Downloading 24 images concurrently...",
        sim_log_download_success_24: "[Downloader] Download completed for 24 images (Avg. 4.8MB/s).",
        sim_log_sys_success_pinterest: "[System] Scraping campaign completed in 4.2s.",

        sim_log_static_mode: "[System] Scraper engine: Static Parser (httpx - maximum speed).",
        sim_log_bypass_proxy: "[System] Proxy skipped (using Local IP to optimize connection speed).",
        sim_log_http_get: "[Static] Dispatching HTTP GET request...",
        sim_log_http_200: "[Static] Server returned: 200 OK in 180ms.",
        sim_log_dom_parse: "[Parser] Traversing HTML DOM tree...",
        sim_log_shopify_catalog: "[Parser] Identified product catalog structure with 50 products.",
        sim_log_shopify_extract: "[Parser] Extracted metadata: Title, Price, SKU, Variants, and Images.",
        sim_log_export_shopify: "[Exporter] Exported Excel catalog sheet: /output/shopify_all.xlsx",
        sim_log_sys_success_shopify: "[System] Processed 50 catalog items in 1.5s."
    }
};

let currentLang = localStorage.getItem('lang') || 'vi';

function t(key, params = {}) {
    const translation = resources[currentLang] || resources['vi'];
    let text = translation[key] || key;
    
    Object.keys(params).forEach(paramKey => {
        text = text.replace(new RegExp(`\\{${paramKey}\\}`, 'g'), params[paramKey]);
    });
    
    return text;
}

function applyTranslations() {
    const translation = resources[currentLang];
    if (!translation) return;

    // Standard texts
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (translation[key]) {
            el.textContent = translation[key];
        }
    });

    // Placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (translation[key]) {
            el.setAttribute('placeholder', translation[key]);
        }
    });

    // Ribbons
    document.querySelectorAll('[data-i18n-badge]').forEach(el => {
        const key = el.getAttribute('data-i18n-badge');
        if (translation[key]) {
            el.setAttribute('data-badge', translation[key]);
        }
    });

    // Page title
    if (translation['meta_title']) {
        document.title = translation['meta_title'];
    }
    
    // Page description meta
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc && translation['meta_description']) {
        metaDesc.setAttribute('content', translation['meta_description']);
    }

    // Open Graph / Social previews
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle && translation['meta_title']) {
        ogTitle.setAttribute('content', translation['meta_title']);
    }
    const ogDesc = document.querySelector('meta[property="og:description"]');
    if (ogDesc && translation['meta_description']) {
        ogDesc.setAttribute('content', translation['meta_description']);
    }

    // Twitter cards
    const twitterTitle = document.querySelector('meta[property="twitter:title"]');
    if (twitterTitle && translation['meta_title']) {
        twitterTitle.setAttribute('content', translation['meta_title']);
    }
    const twitterDesc = document.querySelector('meta[property="twitter:description"]');
    if (twitterDesc && translation['meta_description']) {
        twitterDesc.setAttribute('content', translation['meta_description']);
    }

    // Trigger pricing matrix display sync
    if (typeof updatePricingDisplay === 'function') {
        updatePricingDisplay();
    }
}

function changeLanguage(lang) {
    if (resources[lang]) {
        currentLang = lang;
        localStorage.setItem('lang', lang);
        document.documentElement.setAttribute('lang', lang);
        
        // Sync language selector value
        const select = document.getElementById('language-select');
        if (select) select.value = lang;

        applyTranslations();
    }
}

// Initial setup
document.addEventListener('DOMContentLoaded', () => {
    document.documentElement.setAttribute('lang', currentLang);
    const select = document.getElementById('language-select');
    if (select) {
        select.value = currentLang;
    }
    applyTranslations();
});

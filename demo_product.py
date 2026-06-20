import asyncio
from webharvest.pipeline import ProductCrawlPipeline

async def main():
    print("Running WebHarvest Product Crawl Demo...")
    # Using a Wikipedia page as a generic test page (since it's reliable to fetch without proxies/JS)
    pipeline = ProductCrawlPipeline(
        urls=["https://en.wikipedia.org/wiki/Python_(programming_language)"],
        output_dir="./output_demo_products",
        max_products=1
    )
    
    def on_progress(event, data):
        print(f"[EVENT] {event}: {data}")

    pipeline.on_progress = on_progress
    results = await pipeline.run()
    
    print("\n--- Summary Results ---")
    print(f"Extracted {len(results)} products.")
    for p in results:
        print(f"- Title: {p.title}")
        print(f"  URL: {p.url}")
        print(f"  Price: {p.price}")
        print(f"  Image: {p.main_image_url}")

if __name__ == "__main__":
    asyncio.run(main())

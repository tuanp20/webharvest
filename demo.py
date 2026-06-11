import asyncio
from webharvest import CrawlConfig, CrawlPipeline

async def main():
    print("Running WebHarvest Demo script...")
    config = CrawlConfig(
        url="https://example.com",
        output_dir="./output_demo",
        depth=0,
        concurrent_downloads=5,
    )
    
    pipeline = CrawlPipeline(config)
    result = await pipeline.run()
    
    print("\n--- Summary Results ---")
    print(result.summary())

if __name__ == "__main__":
    asyncio.run(main())

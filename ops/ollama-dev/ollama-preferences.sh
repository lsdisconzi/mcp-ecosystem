# Keep the model loaded permanently
export OLLAMA_KEEP_ALIVE=-1

# 32 GiB RAM means you can use a huge context window
export OLLAMA_NUM_CTX=32768   # or even 65536 for long documents

# Flash attention helps CPU inference as well (reduces memory traffic)
export OLLAMA_FLASH_ATTENTION=1

# Quantised KV cache to save RAM
export OLLAMA_KV_CACHE_TYPE=q8_0
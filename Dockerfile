# Etch MCP server — container image (stdio transport).
#
# WHY slim + apt: cairosvg needs system cairo/pango libraries that pip
# cannot provide. Fonts: the pinned brand TTFs in engine/fonts/ are
# installed to the system font dir so fontconfig resolves them exactly
# as on the dev machine (same file = same metrics = same pixels).
#
# Build:  docker build -t etch-mcp .
# Run:    docker run -i --rm etch-mcp
#         (stdio: attach the container's stdin/stdout to your MCP client)

FROM python:3.12-slim

# System libs for cairosvg + fontconfig tooling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        fonts-dejavu \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY engine/requirements.txt ./engine/requirements.txt
RUN pip install --no-cache-dir -r engine/requirements.txt

COPY engine/ ./engine/

# Pin the brand fonts so renders are identical inside and outside the image.
COPY engine/fonts/*.ttf /usr/share/fonts/truetype/etch/
RUN fc-cache -f /usr/share/fonts/truetype/etch/

# No secrets baked in. ETCH_API_KEY is a REST-API concern; the MCP server
# over stdio inherits the client's trust boundary (local process).
CMD ["python", "engine/mcp_server.py"]

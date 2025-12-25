import apex

agent = apex.from_curl(
    name="Slack Notifier",
    curl='''
    curl -X POST "https://api.segmind.com/v1/flux-2-flex" \
        -H "x-api-key: SG_d9dba9625433e54a" \
        -H "Content-Type: application/json" \
        -d '{
        "prompt": "Soft, weightless 3D letters shaped from glowing, vapor-like aurora mist spelling “Flex”, drifting gently above a crystalline tundra at polar twilight. The colors shift between icy teal, luminescent violet, and pale arctic rose, with diaphanous wisps curling from the edges like illuminated fog. The scene is set inside a vast glacier cavern filled with refractive ice columns and shimmering frost patterns that catch and scatter the ambient light. Shot on Cinestill 800T with a Hasselblad 503CW—cool cinematic tones, gentle halation around the luminous mist-letters, and crisp detail on the faceted ice. A holographic expedition beacon stands in the background, its soft projection displaying “Try FLUX.2 Flex on Segmind!” against the glowing walls, with drifting snow crystals suspended in the still, icy air.",
        "prompt_upsampling": true,
        "seed": 42,
        "width": 1024,
        "height": 1024,
        "safety_tolerance": 2,
        "guidance": 5,
        "steps": 50,
        "output_format": "png"
        }'
    ''',
    price=apex.Fixed(0.25),
)

agent.serve(port=8001)
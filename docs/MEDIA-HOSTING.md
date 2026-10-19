# Media transport

No public temporary file hosts are used. Hugging Face Gradio uploads source files directly to the configured Space; ElevenLabs receives audio through multipart API requests; OpenAI receives chosen source/reference samples. OpenArt receives local source and identity files through its authenticated official upload contract only when an authorized job is prepared for submission.

The app and job media remain served on loopback. There is no cloudflared process or webhook receiver. Old `MEDIA_HOST`, Catbox, Tmpfiles and Enhancor webhook settings are ignored. Provider processing uploads media to those selected services; local paths do not mean local inference. Never log credentials or private signed URLs.

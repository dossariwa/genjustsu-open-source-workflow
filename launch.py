"""Launch only the local UI. OpenArt needs no public host or callback tunnel."""
from config import setting

def main():
    import uvicorn
    uvicorn.run('app:app', host='127.0.0.1', port=int(setting('PORT', '8770')))

if __name__ == '__main__':
    main()

'''
Function:
    Implementation of YouTubeMusicClient: https://music.youtube.com/
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import os
import re
import copy
import time
import base64
import random
import requests
from typing import Any
from bs4 import BeautifulSoup
from ytmusicapi import YTMusic
from contextlib import suppress
from .base import BaseMusicClient
from rich.progress import Progress
from pathvalidate import sanitize_filepath
from ..utils.spotifyutils import SpotubeSecureClient
from urllib.parse import urlencode, urlunsplit, parse_qsl, urlsplit
from ..utils.youtubeutils import YouTube, Stream as YouTubeStreamObj, REPAIDAPI_KEYS
from ..utils import legalizestring, resp2json, usesearchheaderscookies, usedownloadheaderscookies, safeextractfromdict, SongInfo, SongInfoUtils, AudioLinkTester, LyricSearchClient, IOUtils


'''YouTubeMusicClient'''
class YouTubeMusicClient(BaseMusicClient):
    source = 'YouTubeMusicClient'
    def __init__(self, **kwargs):
        super(YouTubeMusicClient, self).__init__(**kwargs)
        self.default_search_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}
        self.default_download_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}
        self.default_headers = self.default_search_headers
        self._initsession()
    '''_download'''
    @usedownloadheaderscookies
    def _download(self, song_info: SongInfo, request_overrides: dict = None, downloaded_song_infos: list = [], progress: Progress = None, song_progress_id: int = 0, auto_supplement_song: bool = True):
        # fallback to general music download method
        if isinstance(song_info.download_url, str): return super()._download(song_info=song_info, request_overrides=request_overrides, downloaded_song_infos=downloaded_song_infos, progress=progress, song_progress_id=song_progress_id, auto_supplement_song=auto_supplement_song)
        # deal with youtube stream object
        song_info, request_overrides = copy.deepcopy(song_info), copy.deepcopy(request_overrides or {}); assert isinstance(song_info.download_url, YouTubeStreamObj)
        song_info._save_path = sanitize_filepath(song_info.save_path); song_info.work_dir = os.path.dirname(song_info.save_path); IOUtils.touchdir(song_info.work_dir)
        try:
            total_size, chunk_size, downloaded_size = int(song_info.download_url.filesize), song_info.chunk_size, 0
            progress.update(song_progress_id, total=total_size if total_size > 0 else None)
            with open(song_info.save_path, "wb") as fp:
                for chunk in song_info.download_url.iterchunks(chunk_size=chunk_size):
                    if chunk: fp.write(chunk); downloaded_size += len(chunk)
                    downloading_text = "%0.2fMB/%0.2fMB" % (downloaded_size / 1024 / 1024, total_size / 1024 / 1024) if total_size > 0 else "%0.2fMB/%0.2fMB" % (downloaded_size / 1024 / 1024, downloaded_size / 1024 / 1024)
                    (total_size == 0) and progress.update(song_progress_id, total=downloaded_size); progress.advance(song_progress_id, len(chunk))
                    progress.update(song_progress_id, description=f"{self.source}._download >>> {song_info.song_name[:15] + '...' if len(song_info.song_name) > 18 else song_info.song_name[:18]} (Downloading: {downloading_text})")
            progress.update(song_progress_id, description=f"{self.source}._download >>> {song_info.song_name[:15] + '...' if len(song_info.song_name) > 18 else song_info.song_name[:18]} (Success)")
            downloaded_song_infos.append(SongInfoUtils.supplsonginfothensavelyricsthenwritetags(song_info, logger_handle=self.logger_handle, disable_print=self.disable_print) if auto_supplement_song else song_info)
        except Exception as err:
            progress.update(song_progress_id, description=f"{self.source}._download >>> {song_info.song_name[:15] + '...' if len(song_info.song_name) > 18 else song_info.song_name[:18]} (Error: {err})")
            self.logger_handle.error(f"{self.source}._download >>> {song_info.song_name[:15] + '...' if len(song_info.song_name) > 18 else song_info.song_name[:18]} (Error: {err})", disable_print=self.disable_print)
        # return
        return downloaded_song_infos
    '''_constructsearchurls'''
    def _constructsearchurls(self, keyword: str, rule: dict = None, request_overrides: dict = None):
        # init
        rule, request_overrides, decrypt_func = rule or {}, request_overrides or {}, lambda t: base64.b64decode(str(t).encode('utf-8')).decode('utf-8')
        ytmusic_search_api = YTMusic(auth=rule.get('auth'), user=rule.get('user'), requests_session=None, proxies=request_overrides.get('proxies') or self._autosetproxies(), language=rule.get('language', 'en'), location=rule.get('location', ''), oauth_credentials=rule.get('oauth_credentials')).search
        rapidapi_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36", "X-Rapidapi-Host": "youtube-music-api3.p.rapidapi.com", "X-Rapidapi-Key": decrypt_func(random.choice(REPAIDAPI_KEYS)), "Referer": "https://music-download-lake.vercel.app/", "Origin": "https://music-download-lake.vercel.app", "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"}
        # construct search urls
        self.search_size_per_page = self.search_size_per_source
        ytmusic_search_rule = {'query': keyword, 'filter': rule.get('filter'), 'scope': rule.get('scope'), 'limit': self.search_size_per_source, 'ignore_spelling': rule.get('ignore_spelling', False)}
        rapidapi_search_rule = {'headers': rapidapi_headers, 'params': {'q': keyword, 'type': 'song', 'limit': self.search_size_per_source}, 'url': 'https://youtube-music-api3.p.rapidapi.com/search'}
        search_urls = [{'candidate_apis': [{'api': self.get, 'inputs': rapidapi_search_rule, 'method': 'rapidapi'}, {'api': ytmusic_search_api, 'inputs': ytmusic_search_rule, 'method': 'ytmusicapi'}]}]
        # return
        return search_urls
    '''_parsewithmp3youtube'''
    def _parsewithmp3youtube(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        mp3youtube_request_key = resp2json(resp=requests.get('https://api.mp3youtube.cc/v2/sanity/key', headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36", "Content-Type": "application/json", "Origin": "https://iframe.y2meta-uk.com", "Accept": "*/*"}, timeout=10, **request_overrides))['key']
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse
        audio_payload = {"link": f"https://youtu.be/{song_id}", "format": "mp3", "audioBitrate": "320", "videoQuality": "720", "vCodec": "h264"}
        (resp := requests.post('https://api.mp3youtube.cc/v2/converter', json=audio_payload, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36", "Content-Type": "application/json", "Origin": "https://iframe.y2meta-uk.com", "Accept": "*/*", "key": mp3youtube_request_key}, timeout=10, **request_overrides)).raise_for_status()
        if not (download_url := (download_result := resp2json(resp=resp)).get('url')) or not str(download_url).startswith('http'): return song_info
        (resp := requests.get(download_url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}, **request_overrides)).raise_for_status()
        download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        if download_url_status['file_size'] in {'NULL'}: download_url_status['file_size_bytes'], download_url_status['file_size'] = resp.content.__sizeof__(), SongInfoUtils.byte2mb(resp.content.__sizeof__())
        duration_in_secs = int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
            file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, downloaded_contents=resp.content, 
        )
        song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # return
        return song_info
    '''_parsewithacethinker'''
    def _parsewithacethinker(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        (resp := requests.get('https://www.acethinker.ai/downloader/api/get_csrf_token.php', headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}, **request_overrides)).raise_for_status()
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36", "accept": "application/json, text/plain, */*", "referer": "https://www.acethinker.ai/freemp3finder", "x-csrf-token": resp2json(resp=resp)['token']}
        (resp := requests.get(f'https://www.acethinker.ai/downloader/api/dlapinewv2.php?url=https://www.youtube.com/watch?v={song_id}', headers=headers, **request_overrides)).raise_for_status()
        medias: list[dict[str, Any]] = (download_result := resp2json(resp=resp)['res_data'])['formats']; medias = [a for a in medias if isinstance(a, dict) and str(a.get('vcodec')).lower() in {"", "none"}]
        for media in sorted(medias, key=lambda x: int(float(x.get('filesize', 0) or 0)), reverse=True):
            if not (download_url := media.get('url')) or not str(download_url).startswith('http'): continue
            download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
            download_url_status['file_size_bytes'] = int(float(media.get('filesize', 0) or 0)) if download_url_status['file_size'] in {'NULL'} else download_url_status['file_size_bytes']
            download_url_status['file_size'] = SongInfoUtils.byte2mb(int(float(media.get('filesize', 0) or 0))) if download_url_status['file_size'] in {'NULL'} else download_url_status['file_size']
            duration_in_secs = int(float(download_result.get('duration') or 0)) or int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
            song_info = SongInfo(
                raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
                file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, default_download_headers=self.default_download_headers,
            )
            song_info.ext, song_info.cover_url = 'm4a' if song_info.ext in {'mp4', 'm4a', 'weba'} else song_info.ext, song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
            if song_info.with_valid_download_url and song_info.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
            with suppress(Exception): (resp := requests.get(f'https://www.acethinker.ai/downloader/api/newytdlapi/youtube_mp3_audio_video_downloader.php?url=https://www.youtube.com/watch?v={song_id}', headers=headers, **request_overrides)).raise_for_status()
            if not (download_url := resp2json(resp=resp).get('download_url')) or not str(download_url).startswith('http'): continue
            download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
            download_url_status['file_size_bytes'] = int(float(media.get('filesize', 0) or 0)) if download_url_status['file_size'] in {'NULL'} else download_url_status['file_size_bytes']
            download_url_status['file_size'] = SongInfoUtils.byte2mb(int(float(media.get('filesize', 0) or 0))) if download_url_status['file_size'] in {'NULL'} else download_url_status['file_size']
            duration_in_secs = int(float(download_result.get('duration') or 0)) or int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
            song_info = SongInfo(
                raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
                file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, default_download_headers=self.default_download_headers,
            )
            song_info.ext, song_info.cover_url = 'm4a' if song_info.ext in {'mp4', 'm4a', 'weba'} else song_info.ext, song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
            if song_info.with_valid_download_url and song_info.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
        # return
        return song_info
    '''_parsewithspotubedlapi'''
    def _parsewithspotubedlapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse
        download_result = SpotubeSecureClient().getdownloadinfobyvideoid(song_id, 'v1', 'mp3', quality='320', request_overrides=request_overrides)
        download_url_status: dict = self.audio_link_tester.test(url=(download_url := SpotubeSecureClient.extractflagurl(download_result)), request_overrides=request_overrides, renew_session=True)
        (resp := requests.get(download_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}, **request_overrides)).raise_for_status()
        if download_url_status['file_size'] in {'NULL'}: download_url_status['file_size_bytes'], download_url_status['file_size'] = resp.content.__sizeof__(), SongInfoUtils.byte2mb(resp.content.__sizeof__())
        duration_in_secs = int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
            file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, downloaded_contents=resp.content, 
        )
        song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # return
        return song_info
    '''_parsewithy2mateapi'''
    def _parsewithy2mateapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        key_url, converter_url, base_headers = "https://cnv.cx/v2/sanity/key", "https://cnv.cx/v2/converter", {"origin": "https://frame.y2meta-uk.com", "referer": "https://frame.y2meta-uk.com/", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"}
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse
        # --key
        (resp := requests.get(key_url, headers=base_headers, **request_overrides)).raise_for_status()
        # --converter
        (converter_headers := base_headers.copy())["key"] = (download_result := resp2json(resp=resp)).get("key")
        converter_headers["content-type"] = "application/x-www-form-urlencoded"
        payload = {"link": f"https://youtu.be/{song_id}", "format": "mp3", "audioBitrate": "320", "videoQuality": "720", "filenameStyle": "pretty", "vCodec": "h264"}
        (resp := requests.post(converter_url, headers=converter_headers, data=payload, **request_overrides)).raise_for_status()
        download_result['converter'] = resp2json(resp=resp); download_url = download_result['converter']['url']
        # --download
        (resp := requests.get(download_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}, **request_overrides)).raise_for_status()
        download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        if download_url_status['file_size'] in {'NULL'}: download_url_status['file_size_bytes'], download_url_status['file_size'] = resp.content.__sizeof__(), SongInfoUtils.byte2mb(resp.content.__sizeof__())
        duration_in_secs = int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
            file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, downloaded_contents=resp.content, 
        )
        song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # return
        return song_info
    '''_parsewithy2matenuapi'''
    def _parsewithy2matenuapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        add_params_func, ts_func = lambda url, params: (lambda parts, query: urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({**query, **params}), parts.fragment)))(urlsplit(url), dict(parse_qsl(urlsplit(str(url)).query, keep_blank_values=True))), lambda: str(int(time.time() * 1000))
        strip_params_func = lambda url: (lambda parts, query: urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({k: v for k, v in query.items() if k not in {'v', 'f', '_'}}), parts.fragment)))(urlsplit(url), dict(parse_qsl(urlsplit(str(url)).query, keep_blank_values=True)))
        auth_url, init_url = "https://eta.etacloud.org/api/v1/auth", "https://eta.etacloud.org/api/v1/init"
        base_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36", "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7", "Origin": "https://v3.y2mate.nu", "Referer": "https://v3.y2mate.nu/"}
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse
        # --auth
        download_result = {}; (resp := requests.get(auth_url, headers=base_headers, params={"_": ts_func()}, **request_overrides)).raise_for_status()
        download_result['auth'] = resp2json(resp=resp); key = download_result['auth'].get('key')
        # --init
        init_headers = base_headers.copy(); init_headers["Authorization"] = f"Bearer {key}"
        (resp := requests.get(init_url, headers=init_headers, params={"_": ts_func()}, **request_overrides)).raise_for_status()
        download_result['init'] = resp2json(resp=resp); convert_url = download_result['init'].get('convertURL')
        # --convert
        convert_url = add_params_func(strip_params_func(convert_url), {"v": song_id, "f": "mp3", "_": ts_func()})
        (resp := requests.get(convert_url, headers=base_headers, **request_overrides)).raise_for_status(); download_result['convert'] = resp2json(resp=resp)
        if download_result['convert'].get('redirect') == 1 and download_result['convert'].get('redirectURL'):
            redirect_url = add_params_func(strip_params_func(download_result['convert']['redirectURL']), {"v": song_id, "f": "mp3", "_": ts_func()})
            (resp := requests.get(redirect_url, headers=base_headers, **request_overrides)).raise_for_status()
            download_result['redirect_convert'] = resp2json(resp=resp); download_result['convert'] = download_result['redirect_convert']
        # --download
        download_url = download_result['convert'].get('downloadURL'); download_url = add_params_func(download_url, {"v": song_id, "f": "mp3", "r": "v3.y2mate.nu"}); download_result['download_url'] = download_url
        download_headers = {"User-Agent": base_headers["User-Agent"], "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8", "Accept-Language": base_headers["Accept-Language"], "Referer": "https://v3.y2mate.nu/"}
        (resp := requests.get(download_url, headers=download_headers, **request_overrides)).raise_for_status()
        # --status
        download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        if download_url_status.get('file_size') in {'NULL', None}: download_url_status['file_size_bytes'] = len(resp.content); download_url_status['file_size'] = SongInfoUtils.byte2mb(len(resp.content))
        # --song info
        duration_in_secs = int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
            file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, downloaded_contents=resp.content, 
        )
        song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # return
        return song_info
    '''_parsewithyt1dapi'''
    def _parsewithyt1dapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        headers, session = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"}, requests.Session()
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # get nonce
        nonce, entry_path, entry_url = None, None, None
        for entry_path_for_test in ["/en77Re/", "/youtube-to-mp380lN/", "/"]:
            with suppress(Exception): entry_url_for_test, resp = f"https://yt1d.io{entry_path_for_test}", None; (resp := session.get(entry_url_for_test, headers=headers, timeout=10, **request_overrides)).raise_for_status()
            if not resp or not hasattr(resp, 'text') or not (nonce_tag := BeautifulSoup(resp.text, 'lxml').find('input', {'name': 'yt1_nonce'})): continue
            if nonce_tag and nonce_tag.get('value'): nonce, entry_path, entry_url = nonce_tag.get('value'), entry_path_for_test, entry_url_for_test
        # parse
        payload = {"yt1_nonce": nonce, "_wp_http_referer": entry_path, "yt_video_url": f'https://www.youtube.com/watch?v={song_id}'}
        headers.update({"Origin": "https://yt1d.io", "Referer": entry_url, "Content-Type": "application/x-www-form-urlencoded"})
        (resp := session.post("https://yt1d.io/results/", data=payload, headers=headers, timeout=15, **request_overrides)).raise_for_status()
        audio_button, download_result = BeautifulSoup(resp.text, 'lxml').find('button', {'class': 'yt1-download-btn', 'data-mode': 'audio'}), str(resp.text)
        if not (download_url := audio_button.get('data-audio-url')):
            token, quality, merge_nonce = audio_button.get('data-token'), audio_button.get('data-quality') or 'MP3', audio_button.get('data-merge-nonce')
            ajax_payload = {"action": "yt1_resolve_streams", "nonce": merge_nonce, "token": token, "quality": quality}; (ajax_headers := headers.copy()).update({"Referer": "https://yt1d.io/results/", "Accept": "*/*"})
            (resp_ajax := session.post("https://yt1d.io/wp-admin/admin-ajax.php", data=ajax_payload, headers=ajax_headers, timeout=15, **request_overrides)).raise_for_status()
            ajax_data_data = (download_result := resp2json(resp=resp_ajax)).get('data') or {}; download_url = ajax_data_data.get('audio_url') or ajax_data_data.get('audioUrl') or ajax_data_data.get('url')
        download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        duration_in_secs = int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), 
            ext=download_url_status['ext'], file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, 
        )
        song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # return
        return song_info
    '''_parsewithmediaytmp3api'''
    def _parsewithmediaytmp3api(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, song_info = request_overrides or {}, search_result['videoId'], SongInfo(source=self.source)
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        song_url, converter_url = f"https://www.youtube.com/watch?v={song_id}", "https://hub.convert1s.com/api/download"
        base_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36", "Accept": "application/json", "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7", "Origin": "https://media.ytmp3.gg", "Referer": "https://media.ytmp3.gg/"}
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse
        # --converter
        download_result, payload = {}, {"url": song_url, "os": "windows", "output": {"type": "audio", "format": "mp3",}, "audio": {"bitrate": "320k"}}
        converter_headers = base_headers.copy(); converter_headers["Content-Type"] = "application/json"
        (resp := requests.post(converter_url, headers=converter_headers, json=payload, **request_overrides)).raise_for_status()
        download_result['converter'] = resp2json(resp=resp); status_url = download_result['converter']['statusUrl']
        # --poll status
        for _ in range(60):
            (resp := requests.get(status_url, headers=base_headers, **request_overrides)).raise_for_status(); download_result['status'] = resp2json(resp=resp)
            if download_result['status'].get('status') == 'completed': break
            time.sleep(1)
        download_url = download_result['status']['downloadUrl']; download_result['download_url'] = download_url
        # --download
        download_headers = {"User-Agent": base_headers["User-Agent"], "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8", "Accept-Language": base_headers["Accept-Language"], "Referer": "https://media.ytmp3.gg/"}
        (resp := requests.get(download_url, headers=download_headers, **request_overrides)).raise_for_status()
        download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        if download_url_status.get('file_size') in {'NULL', None}: download_url_status['file_size_bytes'] = len(resp.content); download_url_status['file_size'] = SongInfoUtils.byte2mb(len(resp.content))
        # --song info
        duration_in_secs = int(float(search_result.get('duration_seconds', 0) or 0)) or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), ext=download_url_status['ext'], 
            file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, downloaded_contents=resp.content, 
        )
        song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # return
        return song_info
    '''_parsewiththirdpartapis'''
    def _parsewiththirdpartapis(self, search_result: dict, request_overrides: dict = None):
        if self.default_cookies or request_overrides.get('cookies'): return SongInfo(source=self.source)
        for parser_func in [self._parsewithy2mateapi, self._parsewithmediaytmp3api, self._parsewithmp3youtube, self._parsewithspotubedlapi, self._parsewithy2matenuapi, self._parsewithacethinker, self._parsewithyt1dapi]:
            song_info_flac = SongInfo(source=self.source, raw_data={'search': search_result, 'download': {}, 'lyric': {}})
            with suppress(Exception): song_info_flac = parser_func(search_result, request_overrides)
            if song_info_flac.with_valid_download_url and song_info_flac.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
        return song_info_flac
    '''_getsongmetainfo'''
    def _getsongmetainfo(self, song_id, request_overrides: dict = None):
        ytmusic = YTMusic(proxies=(request_overrides := request_overrides or {}).get('proxies') or self._autosetproxies())
        with suppress(Exception): data = {}; data = ytmusic.get_watch_playlist(videoId=song_id, limit=1)
        return safeextractfromdict(data, ['tracks', 0], {}) or {}
    '''_parsewithofficialapiv1'''
    def _parsewithofficialapiv1(self, search_result: dict, song_info_flac: SongInfo = None, lossless_quality_is_sufficient: bool = True, lossless_quality_definitions: set | list | tuple = {'flac'}, request_overrides: dict = None) -> "SongInfo":
        # init
        song_info, request_overrides, song_info_flac = SongInfo(source=self.source), request_overrides or {}, song_info_flac or SongInfo(source=self.source)
        if (not isinstance(search_result, dict)) or (not (song_id := search_result.get('videoId'))): return song_info
        to_seconds_func = lambda x: (lambda s: 0 if not s else (lambda p: p[-3]*3600+p[-2]*60+p[-1] if len(p)>=3 else p[0]*60+p[1] if len(p)==2 else p[0] if len(p)==1 else 0)([int(v) for v in re.findall(r'\d+', s.replace('：', ':'))]) if (':' in s or '：' in s) else (lambda h,m,sec,num: (lambda tot: tot if tot>0 else num)(h*3600+m*60+sec))(int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:小时|时|h|hr)', s)) else 0, int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:分钟|分|m|min)', s)) else 0, (int(mo.group(1)) if (mo:=re.search(r'(\d+)\s*(?:秒|s|sec)', s)) else (int(mo.group(1)) if (mo:=re.search(r'(?:分钟|分|m|min)\s*(\d+)\b', s)) else 0)), int(mo.group(0)) if (mo:=re.search(r'\d+', s)) else 0))(str(x).strip().lower())
        codec_to_ext_func = lambda c: next((str(ext).removeprefix('.') for k, ext in {"mp4a": ".m4a", "flac": ".flac", "opus": ".opus", "vorbis": ".ogg", "mp3": ".mp3", "aac": ".aac", "alac": ".m4a", "pcm": ".wav", "wav": ".wav"}.items() if str((c[0] if isinstance(c, (list, tuple)) else c)).lower().startswith(k)), None)
        if not search_result.get('title'): search_result.update(self._getsongmetainfo(song_id=song_id, request_overrides=request_overrides))
        # parse download url based on arguments
        if lossless_quality_is_sufficient and song_info_flac.with_valid_download_url and (song_info_flac.ext in lossless_quality_definitions): song_info = song_info_flac
        else:
            download_url: YouTubeStreamObj = (cli := YouTube(video_id=search_result['videoId'])).streams.getaudioonly()
            duration_in_secs = (float(download_url.durationMs) / 1000) or search_result.get('duration_seconds') or to_seconds_func(search_result.get('duration') or search_result.get('length') or '0:00')
            song_info = SongInfo(
                raw_data={'search': search_result, 'download': cli.vid_info, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(search_result.get('author') or (', '.join([singer.get('name') for singer in (search_result.get('artists') or []) if isinstance(singer, dict) and singer.get('name')]))), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None) or search_result.get('album')), 
                ext=codec_to_ext_func(download_url.audio_codec), file_size_bytes=download_url.filesize, file_size=SongInfoUtils.byte2mb(download_url.filesize), identifier=song_id, duration_s=duration_in_secs, duration=SongInfoUtils.seconds2hms(duration_in_secs), lyric=None, cover_url=search_result.get('thumbnail') or safeextractfromdict(search_result, ['thumbnails', -1, 'url'], None), download_url=download_url, download_url_status={'ok': True}, 
            )
            song_info.cover_url = song_info.cover_url[-1]['url'] if isinstance(song_info.cover_url, (list, tuple)) else song_info.cover_url
        # compare and select the best
        song_info = song_info_flac if song_info_flac.with_valid_download_url and (not song_info.with_valid_download_url or song_info_flac.largerthan(song_info)) else song_info
        if not song_info.with_valid_download_url or song_info.ext not in AudioLinkTester.VALID_AUDIO_EXTS: return song_info
        if not song_info.duration or song_info.duration == '00:00:00': song_info.duration_s = locals().get('duration_in_secs'); song_info.duration = SongInfoUtils.seconds2hms(song_info.duration_s)
        # supplement lyric results
        lyric_result, lyric = LyricSearchClient().search(artist_name=song_info.singers, track_name=song_info.song_name, request_overrides=request_overrides)
        song_info.raw_data['lyric'] = lyric_result if lyric_result else song_info.raw_data['lyric']
        song_info.lyric = lyric if (lyric and (lyric not in {'NULL'})) else song_info.lyric
        # return
        return song_info
    '''_search'''
    @usesearchheaderscookies
    def _search(self, keyword: str = '', search_url: dict = {}, request_overrides: dict = None, song_infos: list = [], progress: Progress = None, progress_id: int = 0):
        # init
        request_overrides, candidate_apis, page_no = request_overrides or {}, copy.deepcopy(search_url)['candidate_apis'], 1
        # successful
        try:
            # --search results
            ytmusicapi_candidate_api: dict = [c for c in candidate_apis if c['method'] in {'ytmusicapi'}][0]; rapidapi_candidate_api: dict = [c for c in candidate_apis if c['method'] in {'rapidapi'}][0]
            with suppress(Exception): search_results = None; resp = ytmusicapi_candidate_api['api'](**ytmusicapi_candidate_api['inputs']); search_results = [s for s in resp if s['resultType'] == 'song']
            if not search_results: resp = rapidapi_candidate_api['api'](**rapidapi_candidate_api['inputs']); search_results = resp2json(resp=resp)['result']
            task_id = progress.add_task(f"{self.source}._search >>> Start to process the 0th search result on page {page_no}", total=None, completed=0)
            for search_result_idx, search_result in enumerate(search_results or list()):
                # --update progress
                progress.update(task_id, description=f'{self.source}._search >>> Start to process the {search_result_idx+1}th search result on page {page_no}', completed=search_result_idx+1, total=search_result_idx+1)
                # --init song info
                song_info = SongInfo(source=self.source, raw_data={'search': search_result, 'download': {}, 'lyric': {}})
                # --parse with third part apis
                song_info_flac = self._parsewiththirdpartapis(search_result=search_result, request_overrides=request_overrides)
                # --parse with official apis
                with suppress(Exception): song_info = self._parsewithofficialapiv1(search_result=search_result, song_info_flac=song_info_flac, lossless_quality_is_sufficient=False, request_overrides=request_overrides)
                # --append to song_infos
                if (song_info := song_info if song_info.with_valid_download_url else song_info_flac).with_valid_download_url: song_infos.append(song_info)
                # --judgement for search_size
                if self.strict_limit_search_size_per_page and len(song_infos) >= self.search_size_per_page: break
            # --update progress
            progress.update(progress_id, description=f"{self.source}._search >>> {search_url} (Success)")
        # failure
        except Exception as err:
            progress.update(progress_id, description=f"{self.source}._search >>> {search_url} (Error: {err})")
            self.logger_handle.error(f"{self.source}._search >>> {search_url} (Error: {err})", disable_print=self.disable_print)
        # return
        return song_infos
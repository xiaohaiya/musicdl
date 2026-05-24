'''
Function:
    Implementation of WJHEMusicClient: https://music.wjhe.top/
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import re
import copy
import time
from contextlib import suppress
from rich.progress import Progress
from ..sources import BaseMusicClient
from urllib.parse import urlencode, parse_qs, urlparse
from ..utils import legalizestring, usesearchheaderscookies, resp2json, safeextractfromdict, extractdurationsecondsfromlrc, SongInfo, SongInfoUtils, AudioLinkTester, LyricSearchClient


'''WJHEMusicClient'''
class WJHEMusicClient(BaseMusicClient):
    source = 'WJHEMusicClient'
    ALLOWED_SITES = ['qobuz', 'migu', 'joox']
    def __init__(self, **kwargs):
        self.allowed_music_sources = list(set(kwargs.pop('allowed_music_sources', WJHEMusicClient.ALLOWED_SITES[1:])))
        super(WJHEMusicClient, self).__init__(**kwargs)
        self.default_search_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36", "Referer": "https://music.wjhe.top/"}
        self.default_download_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36", "Referer": "https://music.wjhe.top/"}
        self.default_headers = self.default_search_headers
        self._initsession()
    '''_constructsearchurls'''
    def _constructsearchurls(self, keyword: str, rule: dict = None, request_overrides: dict = None):
        # init
        rule, request_overrides, allowed_music_sources = rule or {}, request_overrides or {}, copy.deepcopy(self.allowed_music_sources)
        # construct search urls
        base_url, search_urls, page_size = 'https://music.wjhe.top/api/music/{}/search?', [], self.search_size_per_page
        for source in WJHEMusicClient.ALLOWED_SITES:
            if source not in allowed_music_sources: continue
            (source_default_rule := {'key': keyword, 'pageIndex': 1, 'pageSize': page_size, '_': str(int(time.time() * 1000))}).update(rule); count = 0
            while self.search_size_per_source > count:
                (page_rule := copy.deepcopy(source_default_rule))['pageIndex'] = str(int(count // page_size) + 1)
                search_urls.append(base_url.format(source) + urlencode(page_rule))
                count += page_size
        # return
        return search_urls
    '''_search'''
    @usesearchheaderscookies
    def _search(self, keyword: str = '', search_url: str = None, request_overrides: dict = None, song_infos: list = [], progress: Progress = None, progress_id: int = 0):
        # init
        request_overrides, root_source = request_overrides or {}, re.search(r'/api/music/([^/]+)/search\?', search_url).group(1)
        page_no = int(float(parse_qs(urlparse(url=search_url).query, keep_blank_values=True).get('pageIndex')[0]))
        # successful
        try:
            # --search results
            (resp := self.get(search_url, **request_overrides)).raise_for_status()
            task_id = progress.add_task(f"{self.source}._search >>> Start to process the 0th search result on page {page_no}", total=None, completed=0)
            for search_result_idx, search_result in enumerate(resp2json(resp)['data']['data']):
                # --update progress
                progress.update(task_id, description=f'{self.source}._search >>> Start to process the {search_result_idx+1}th search result on page {page_no}', completed=search_result_idx+1, total=search_result_idx+1)
                # --download results
                if not isinstance(search_result, dict) or (not (song_id := search_result.get('ID'))) or (not search_result.get('fileLinks')): continue
                search_result['source'], song_info = root_source, SongInfo(source=self.source, root_source=root_source), 
                for file_link_info in sorted(search_result['fileLinks'], key=lambda fl: float(fl['quality']), reverse=True):
                    download_url = f"https://music.wjhe.top/api/music/{root_source}/url?ID={song_id}&quality={file_link_info['quality']}&format={file_link_info['format']}"
                    if (download_url_status := self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True))['ok']: break
                cover_url = f"https://music.wjhe.top/api/music/{root_source}/url?ID={song_id}&quality=500&format=jpg"
                with suppress(Exception): cover_url = self.session.head(cover_url, timeout=10, allow_redirects=True, **request_overrides).url
                song_info = SongInfo(
                    raw_data={'search': search_result, 'download': {}, 'lyric': {}}, source=self.source, song_name=legalizestring(search_result.get('name') or search_result.get('title')), singers=legalizestring(', '.join([singer.get('name') for singer in (safeextractfromdict(search_result, ['singers'], []) or []) if isinstance(singer, dict) and singer.get('name')])), album=legalizestring(safeextractfromdict(search_result, ['album', 'name'], None)), 
                    ext=download_url_status['ext'], file_size_bytes=download_url_status['file_size_bytes'], file_size=download_url_status['file_size'], identifier=song_id, duration_s=search_result.get('duration'), duration=SongInfoUtils.seconds2hms(search_result.get('duration')), lyric=None, cover_url=cover_url, download_url=download_url_status['download_url'], download_url_status=download_url_status, root_source=search_result['source'],
                )
                if not song_info.with_valid_download_url or song_info.ext not in AudioLinkTester.VALID_AUDIO_EXTS: continue
                # --lyric results
                lyric_result, lyric = LyricSearchClient().search(artist_name=song_info.singers, track_name=song_info.song_name, request_overrides=request_overrides)
                song_info.raw_data['lyric'] = lyric_result if lyric_result else song_info.raw_data['lyric']
                song_info.lyric = lyric if (lyric and (lyric not in {'NULL'})) else song_info.lyric
                if song_info.duration == '-:-:-': song_info.duration_s = extractdurationsecondsfromlrc(song_info.lyric); song_info.duration = SongInfoUtils.seconds2hms(song_info.duration_s)
                # --append to song_infos
                if song_info.with_valid_download_url: song_infos.append(song_info)
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
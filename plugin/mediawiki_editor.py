from __future__ import print_function
import sys

try:
    import mwclient
except ImportError:
    sys.stderr.write(
        'mwclient not installed; install perhaps via'
        ' pip install mwclient.\n')
    raise

import six

from_cmdline = False
try:
    __file__
    from_cmdline = True
except NameError:
    pass


if not from_cmdline:
    import vim

VALID_PROTOCOLS = ['http', 'https']

# Utility.


def sq_escape(s):
    return s.replace("'", "''")


def fn_escape(s):
    return vim.eval("fnameescape('%s')" % sq_escape(s))


def input(prompt, text='', password=False):
    vim.command('call inputsave()')
    vim.command("let i = %s('%s', '%s')" % (('inputsecret' if password else 'input'),
                                            sq_escape(prompt), sq_escape(text)))
    vim.command('call inputrestore()')
    return vim.eval('i')


def var_exists(var):
    return bool(int(vim.eval("exists('%s')" % sq_escape(var))))


def get_from_config(var):
    if var_exists(var):
        return vim.eval(var)
    return None


def get_from_config_or_prompt(var, prompt, password=False, text=''):
    c = get_from_config(var)
    if c is not None:
        return c
    else:
        resp = input(prompt, text=text, password=password)
        vim.command("let %s = '%s'" % (var, sq_escape(resp)))
        return resp


def base_url():
    return get_from_config_or_prompt('g:mediawiki_editor_url',
                                     "Mediawiki URL, like 'en.wikipedia.org': ")


def site():
    if site.cached_site:
        return site.cached_site

    scheme = get_from_config('g:mediawiki_editor_uri_scheme')
    if scheme not in VALID_PROTOCOLS:
        scheme = 'https'

    if get_from_config('g:mediawiki_basicauth_enabled'):
        httpauth = (
            get_from_config_or_prompt('g:mediawiki_basicauth_username',
                                      'Basic Auth Username: '),
            get_from_config_or_prompt('g:mediawiki_basicauth_password',
                                      'Basic Auth Password: ', password=True)
        )
    else:
        httpauth = None

    s = mwclient.Site((scheme, base_url()),
                      httpauth=httpauth,
                      path=get_from_config_or_prompt('g:mediawiki_editor_path',
                                                     'Mediawiki Script Path: ',
                                                     text='/w/'))
    try:
        s.login(
            get_from_config_or_prompt('g:mediawiki_editor_username',
                                      'Mediawiki Username: '),
            get_from_config_or_prompt('g:mediawiki_editor_password',
                                      'Mediawiki Password: ', password=True)
        )
    except mwclient.errors.LoginError as e:
        sys.stderr.write('Error logging in: %s\n' % e)
        vim.command(
            'unlet g:mediawiki_editor_username '
            'g:mediawiki_editor_password'
        )
        raise

    site.cached_site = s
    return s


site.cached_site = None


def infer_default(article_name):
    if not article_name:
        article_name = vim.current.buffer.vars.get('article_name')
    else:
        article_name = article_name[0]

    if not article_name:
        sys.stderr.write('No article specified.\n')

    if isinstance(article_name, six.binary_type):
        article_name = article_name.decode('utf-8')
    return article_name


# Commands.

def mw_save_name(article_name):
    vim.command('file %s.wiki' % article_name)
    vim.command("let b:article_name = '%s'" % sq_escape(article_name))

def mw_read(article_name):
    if isinstance(article_name, six.binary_type):
        article_name = article_name.decode('utf-8')
    s = site()
    # make a new special buffer
    vim.command('enew')
    vim.command('setlocal buftype=acwrite')
    vim.command('set ft=mediawiki')
    vim.current.buffer[:] = s.Pages[article_name].text().split("\n")
    vim.command('set nomodified')
    mw_save_name(article_name)
    vim.command('redraw')
    vim.command("echo 'Loaded %s'" % article_name)

def mw_backlinks(article_name):
    article_name = infer_default(article_name)
    s = site()
    backlinks = list(s.Pages[article_name].backlinks())
    if len(backlinks) == 0:
        vim.command("echo 'No backlinks found for %s'" % article_name)
        return
    vim.command('enew')
    vim.command('setlocal buftype=acwrite')
    vim.command('set ft=mediawiki')
    vim.current.buffer[:] = ["[[%s]]" % p.name for p in backlinks]
    mw_save_name("Special:Whatlinkshere/%s" % article_name)
    vim.command('set nomodified')
    vim.command('redraw')
    vim.command("echo 'Retrieved backlinks for %s'" % article_name)

def mw_move(no_redirect, new_name):
    article_name = infer_default(None)

    s = site()
    page = s.Pages[article_name]
    page.move(new_name, no_redirect == 0)
    mw_save_name(new_name)
    vim.command('redraw')
    print("Renamed from {} to {}. No redirect was {}".format(article_name, new_name, no_redirect == 0))

def mw_write(article_name):
    article_name = infer_default(article_name)

    s = site()
    page = s.Pages[article_name]
    summary = input('Edit summary: ')
    minor = input('Minor edit? [y/n]: ') == 'y'

    result = page.save("\n".join(vim.current.buffer[:]), summary=summary,
                       minor=minor)
    if result['result']:
        vim.command('set nomodified')
        vim.command('redraw')
        print('Edited %s' % result['title'])
    else:
        sys.stderr.write('Failed to edit %s.\n' % article_name)


def mw_diff(article_name):
    article_name = infer_default(article_name)

    s = site()
    vim.command('diffthis')
    vim.command('leftabove vsplit %s' % fn_escape(article_name + ' - REMOTE'))
    vim.command('setlocal buftype=nofile bufhidden=delete nobuflisted')
    vim.current.buffer[:] = s.Pages[article_name].text().split("\n")
    vim.command('diffthis')
    vim.command('set nomodifiable')


def mw_search(query_args):
    if not query_args:
        sys.stderr.write('No query passed.\n')
        return

    query = " ".join(query_args)
    if query == "":
        sys.stderr.write('No query passed.\n')
    vim.command("echo 'Retrieving search results for %s...'" % query)
    s = site()
    results = list(s.search(query))

    if len(results) == 0:
        vim.command("echo 'No search results found for %s'" % query)
        return

    vim.command('enew')
    vim.command('setlocal buftype=nowrite')
    vim.command('set ft=mediawiki')
    vim.current.buffer[:] = ["[[%s]]" % p.get('title') for p in results]
    mw_save_name("Search: %s" % query)
    vim.command('set nomodified')
    vim.command('redraw')
    vim.command("echo 'Retrieved search results for %s'" % query)


def mw_subpages(article_name):
    article_name = infer_default(article_name)
    if not article_name:
        sys.stderr.write('No article name, cannot search for subpages\n')
        return

    mw_search(['prefix:%s/' % article_name])


def mw_browse(article_name):
    article_name = infer_default(article_name)

    url = 'http://%s%sindex.php/%s' % (
            base_url(),
            get_from_config('g:mediawiki_editor_path') or "/wiki/",
            article_name)
    if not var_exists('g:loaded_netrw'):
        vim.command('runtime! autoload/netrw.vim')

    if var_exists('*netrw#BrowseX'):
        vim.command("call netrw#BrowseX('%s', 0)" % sq_escape(url))
    else:
        vim.command("call netrw#NetrwBrowseX('%s', 0)" % sq_escape(url))

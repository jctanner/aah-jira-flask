#!/usr/bin/env python

import pytest

from lib.text_tools import render_jira_markup
from lib.text_tools import render_code
from lib.text_tools import replace_headers


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (
            'foo\n{code}\nlet i=1\nlet j=2\n{code}\nbar',
            'foo\n<div class="highlight"><pre><span></span>let i=1\nlet j=2\n</pre></div>\n\nbar'
        ),
        (
            'foo\n{code:javascript}\nlet i=1\nlet j=2\n{code}\nbar',
            (
                'foo\n<div class="highlight"><pre><span></span><span class="kd">let</span><span class="w"> </span><span class="nx">i</span><span class="o">=</span><span class="mf">1</span>\n<span class="kd">let</span><span class="w"> </span><span class="nx">j</span><span class="o">=</span><span class="mf">2</span>\n</pre></div>\n\nbar'
            )
        ),

    ]
)
def test_render_code(test_input, expected):
    assert render_code(test_input) == expected

@pytest.mark.parametrize(
    "test_input,expected",
    [
        ('h1. foobar\r', '<h1> foobar</h1>\r'),
        ('h1.foobar\r', '<h1>foobar</h1>\r'),
        ('h1.foobar\rh1.foobar2\r', '<h1>foobar</h1>\r<h1>foobar2</h1>\r'),
    ]
)
def test_replace_headers(test_input, expected):
    #raw = 'h1. foobar\r'
    #res = replace_headers(raw)
    #assert res == '<h1>foobar</h1>'
    assert replace_headers(test_input) == expected

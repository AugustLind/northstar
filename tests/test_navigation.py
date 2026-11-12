"""Check actual HTML hierarchy, including preserved legacy destinations."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest

class Layout(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.nodes={};self.ids=[];self.buttons=[];self.errors=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id']);self.nodes[attrs['id']]={'attrs':attrs,'ancestors':[a.get('id') for t,a in self.stack]}
        if 'data-tab' in attrs:self.buttons.append(attrs['data-tab'])
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:self.stack.append((tag,attrs))
    def handle_endtag(self,tag):
        if not self.stack or self.stack[-1][0]!=tag:self.errors.append(tag)
        else:self.stack.pop()

class NavigationTests(unittest.TestCase):
    def test_four_workspaces_preserve_merged_tools_and_valid_markup(self):
        layout=Layout();layout.feed((Path(__file__).resolve().parents[1]/'static/index.html').read_text())
        self.assertEqual(layout.errors,[]);self.assertEqual(layout.stack,[])
        self.assertTrue(all(n==1 for n in Counter(layout.ids).values()))
        self.assertEqual(layout.buttons,['daily','recommendations','portfolio','validation'])
        tabs={id for id,node in layout.nodes.items() if 'tab' in node['attrs'].get('class','').split()}
        self.assertEqual(tabs,set(layout.buttons))
        for child,parent in [('announcements','daily'),('briefing','daily'),('method','daily'),('fit','portfolio'),('activity','portfolio')]:
            self.assertIn(parent,layout.nodes[child]['ancestors'])
            self.assertIn(child+'Group',layout.nodes[child]['ancestors'])
        self.assertNotIn('hidden',layout.nodes['daily']['attrs'])
        for id in tabs-{'daily'}:self.assertIn('hidden',layout.nodes[id]['attrs'])

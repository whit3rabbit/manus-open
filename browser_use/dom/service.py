import logging
from datetime import datetime
from importlib import resources
from typing import Optional
from playwright.async_api import Page
from browser_use.dom.history_tree_processor.view import Coordinates
from browser_use.dom.views import CoordinateSet, DOMBaseNode, DOMElementNode, DOMState, DOMTextNode, SelectorMap, ViewportInfo
import json

logger = logging.getLogger(__name__)

class DomService:
    def __init__(self, page):
        self.page = page
        self.xpath_cache = {}
        self.js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')
    
    async def get_clickable_elements(self, highlight_elements=True, focus_element=-1, viewport_expansion=0):
        element_tree, selector_map = await self._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
        return DOMState(element_tree=element_tree, selector_map=selector_map)
    
    async def _build_dom_tree(self, highlight_elements, focus_element, viewport_expansion):
        if await self.page.evaluate('1+1') != 2:
            raise ValueError('The page cannot evaluate javascript code properly')
        
        debug_mode = logger.getEffectiveLevel() == logging.DEBUG
        args = {
            'doHighlightElements': highlight_elements,
            'focusHighlightIndex': focus_element,
            'viewportExpansion': viewport_expansion,
            'debugMode': debug_mode,
        }
        
        try:
            eval_page = await self.page.evaluate(self.js_code, args)
        except Exception as e:
            logger.error('Error evaluating JavaScript: %s', e)
            raise
            
        if debug_mode and 'perfMetrics' in eval_page:
            logger.debug('DOM Tree Building Performance Metrics:\n%s', json.dumps(eval_page['perfMetrics'], indent=2))
            
        return await self._construct_dom_tree(eval_page)
    
    async def _construct_dom_tree(self, eval_page):
        js_node_map = eval_page['map']
        js_root_id = eval_page['rootId']
        
        selector_map = {}
        node_map = {}
        
        for id, node_data in js_node_map.items():
            node, children_ids = self._parse_node(node_data)
            if node is None:
                continue
                
            node_map[id] = node
            
            if isinstance(node, DOMElementNode) and node.highlight_index is not None:
                selector_map[node.highlight_index] = node
                
            if isinstance(node, DOMElementNode):
                for child_id in children_ids:
                    if child_id not in node_map:
                        continue
                        
                    child_node = node_map[child_id]
                    
                    child_node.parent = node
                    node.children.append(child_node)
                    
        html_to_dict = node_map[str(js_root_id)]
        
        if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
            raise ValueError('Failed to parse HTML to dictionary')
            
        return html_to_dict, selector_map
    
    def _create_selector_map(self, element_tree):
        selector_map = {}
        
        def traverse_node(node):
            if isinstance(node, DOMElementNode):
                if node.highlight_index is not None:
                    selector_map[node.highlight_index] = node
                for child in node.children:
                    traverse_node(child)
        
        traverse_node(element_tree)
        return selector_map
    
    def _parse_node(self, node_data, viewport=None, parent=None):
        if not node_data:
            return None, []
            
        # Process text nodes immediately
        if node_data.get('type') == 'TEXT_NODE':
            text_node = DOMTextNode(
                text=node_data['text'],
                is_visible=node_data['isVisible'],
                parent=parent
            )
            return text_node, []
            
        tag_name = node_data['tagName']
        viewport_coordinates = None
        page_coordinates = None
        
        if viewport:
            scroll_x = viewport.scroll_x
            scroll_y = viewport.scroll_y
            
            if 'viewportPos' in node_data:
                x1, y1, x2, y2 = node_data['viewportPos']
                x1 = int(x1)
                y1 = int(y1)
                x2 = int(x2)
                y2 = int(y2)
                width = int(x2 - x1)
                height = int(y2 - y1)
                
                viewport_coordinates = CoordinateSet(
                    top_left=Coordinates(x=x1, y=y1),
                    top_right=Coordinates(x=x2, y=y1),
                    bottom_left=Coordinates(x=x1, y=y2),
                    bottom_right=Coordinates(x=x2, y=y2),
                    center=Coordinates(x=int(x1 + width / 2), y=int(y1 + height / 2)),
                    width=width,
                    height=height
                )
                
                page_coordinates = CoordinateSet(
                    top_left=Coordinates(x=x1 + scroll_x, y=y1 + scroll_y),
                    top_right=Coordinates(x=x2 + scroll_x, y=y1 + scroll_y),
                    bottom_left=Coordinates(x=x1 + scroll_x, y=y2 + scroll_y),
                    bottom_right=Coordinates(x=x2 + scroll_x, y=y2 + scroll_y),
                    center=Coordinates(x=int(x1 + scroll_x + width / 2), y=int(y1 + scroll_y + height / 2)),
                    width=width,
                    height=height
                )
                
        element_node = DOMElementNode(
            tag_name=tag_name,
            xpath=node_data['xpath'],
            attributes=node_data.get('attributes', {}),
            children=[],
            is_visible=node_data.get('isVisible', False),
            is_interactive=node_data.get('isInteractive', False),
            is_top_element=node_data.get('isTopElement', False),
            highlight_index=node_data.get('highlightIndex'),
            shadow_root=node_data.get('shadowRoot', False),
            parent=parent,
            viewport_coordinates=viewport_coordinates,
            page_coordinates=page_coordinates,
            viewport_info=viewport
        )
        
        children_ids = node_data.get('children', [])
        
        return element_node, children_ids
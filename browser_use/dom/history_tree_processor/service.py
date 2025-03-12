import hashlib
from dataclasses import dataclass # in bytecode not accessed?
from typing import Optional # in bytecode not accessed?
from browser_use.dom.history_tree_processor.view import DOMHistoryElement, HashedDomElement
from browser_use.dom.views import DOMElementNode


class HistoryTreeProcessor:
    """
    Operations on the DOM elements

    @dev be careful - text nodes can change even if elements stay the same
    """

    @staticmethod
    def convert_dom_element_to_history_element(dom_element):
        parent_branch_path = HistoryTreeProcessor._get_parent_branch_path(dom_element)
        css_selector = dom_element.get_advanced_css_selector()
        return DOMHistoryElement(
            dom_element.tag_name,
            dom_element.xpath,
            dom_element.highlight_index,
            parent_branch_path,
            dom_element.attributes,
            dom_element.shadow_root,
            css_selector=css_selector,
            page_coordinates=dom_element.page_coordinates,
            viewport_coordinates=dom_element.viewport_coordinates,
            viewport_info=dom_element.viewport_info
        )

    @staticmethod
    def find_history_element_in_tree(dom_history_element, tree):
        hashed_dom_history_element = HistoryTreeProcessor._hash_dom_history_element(dom_history_element)
        
        def process_node(node):
            if node.highlight_index is not None:
                hashed_node = HistoryTreeProcessor._hash_dom_element(node)
                if hashed_node == hashed_dom_history_element:
                    return node
            for child in node.children:
                if isinstance(child, DOMElementNode):
                    result = process_node(child)
                    if result is not None:
                        return result
            return None
            
        return process_node(tree)

    @staticmethod
    def compare_history_element_and_dom_element(dom_history_element, dom_element):
        hashed_dom_history_element = HistoryTreeProcessor._hash_dom_history_element(dom_history_element)
        hashed_dom_element = HistoryTreeProcessor._hash_dom_element(dom_element)
        return hashed_dom_history_element == hashed_dom_element

    @staticmethod
    def _hash_dom_history_element(dom_history_element):
        branch_path_hash = HistoryTreeProcessor._parent_branch_path_hash(dom_history_element.entire_parent_branch_path)
        attributes_hash = HistoryTreeProcessor._attributes_hash(dom_history_element.attributes)
        xpath_hash = HistoryTreeProcessor._xpath_hash(dom_history_element.xpath)
        return HashedDomElement(branch_path_hash, attributes_hash, xpath_hash)

    @staticmethod
    def _hash_dom_element(dom_element):
        parent_branch_path = HistoryTreeProcessor._get_parent_branch_path(dom_element)
        branch_path_hash = HistoryTreeProcessor._parent_branch_path_hash(parent_branch_path)
        attributes_hash = HistoryTreeProcessor._attributes_hash(dom_element.attributes)
        xpath_hash = HistoryTreeProcessor._xpath_hash(dom_element.xpath)
        return HashedDomElement(branch_path_hash, attributes_hash, xpath_hash)

    @staticmethod
    def _get_parent_branch_path(dom_element):
        parents = []
        current_element = dom_element
        while current_element.parent is not None:
            parents.append(current_element)
            current_element = current_element.parent
            
        parents.reverse()
        
        return [parent.tag_name for parent in parents]

    @staticmethod
    def _parent_branch_path_hash(parent_branch_path):
        parent_branch_path_string = '/'.join(parent_branch_path)
        return hashlib.sha256(parent_branch_path_string.encode()).hexdigest()

    @staticmethod
    def _attributes_hash(attributes):
        attributes_string = ''.join(f'{key}={value}' for key, value in attributes.items())
        return hashlib.sha256(attributes_string.encode()).hexdigest()

    @staticmethod
    def _xpath_hash(xpath):
        return hashlib.sha256(xpath.encode()).hexdigest()

    @staticmethod
    def _text_hash(dom_element):
        text_string = dom_element.get_all_text_till_next_clickable_element()
        return hashlib.sha256(text_string.encode()).hexdigest()
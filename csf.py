# -*- encoding: utf-8 -*-
# @File   : csf.py
# @Time   : 2024/01/09 21:17:24
# @Author : Chloride
"""C&C Stringtable Format

Support .csf files IO and JSON, XML files import/export.

The JSON and XML formatting follows [Shimakaze]\
(https://frg2089.github.io)'s schema.
The SIMPLE YAML document, as it described, only support simple value,
with just `label: str` pair form.

Direct operation on CsfDocument instance is also supported,
but in my opinion, way more complex than just editing text files.
"""

import json
import warnings
from collections.abc import Iterator, MutableMapping
from ctypes import c_ubyte
from enum import Enum
from io import FileIO
from re import S as FULL_MATCH
from re import compile as regex
from struct import pack, unpack
from typing import Any, Dict, List, NamedTuple, Optional, TypedDict, Union
from xml.dom import minidom
from xml.etree import ElementTree as et

import yaml

__all__ = ['CSF_TAG', 'LBL_TAG', 'VAL_TAG', 'EVAL_TAG',
           'CsfHead', 'CsfLang', 'CsfVal', 'CsfDocument',
           'InvalidCsfException', 'EditorIncompatibleWarning',
           'csfToJSONV2', 'csfToXMLV1', 'importJSONV2', 'importXMLV1',
           'csfToSimpleYAML', 'importSimpleYAML']


CSF_TAG = " FSC"
LBL_TAG = " LBL"
VAL_TAG = " RTS"
EVAL_TAG = "WRTS"


SHIMAKAZE_SCHEMA = 'https://shimakazeproject.github.io/Schemas'
JSON_HEAD = {
    "$schema": f"{SHIMAKAZE_SCHEMA}/json/csf/v2.json",
    "protocol": 2
}
XML_SCHEMA_TYPENS = 'http://www.w3.org/2001/XMLSchema'
XML_MODEL = ("<?xml-model "
             f'href="{SHIMAKAZE_SCHEMA}/xml/csf/v1.xsd" '
             'type="application/xml" '
             f'schematypens="{XML_SCHEMA_TYPENS}"?>\n')
YAML_SPECIAL_SIGNS_1 = [
    '_', '?', ',', '[', ']', '{', '}', '#', '&', '*', '!', '|',
    '>', '"', '%', ':'
]
YAML_SPECIAL_SIGNS_2 = "'"
YAML_SCHEMA_HEADER = f'# yaml-language-server: \
$schema={SHIMAKAZE_SCHEMA}/yaml/csf/metadata.yaml'
YAML_SCHEMA_BODY = f'# yaml-language-server: \
$schema={SHIMAKAZE_SCHEMA}/yaml/csf/v1.yaml'


class CsfHead(NamedTuple):
    """Only for IO process."""
    version: int  # offset 04H, after CSF_TAG.
    numlabels: int
    numvalues: int
    unused: int
    language: int


class CsfLang(Enum):
    Universal = -1  # Ares implemented
    en_US = 0
    en_UK = 1
    de = 2  # German
    fr = 3  # French
    es = 4  # Spanish
    it = 5  # Italian
    jp = 6  # Japanese
    Jabberwockie = 7
    kr = 8  # Korean
    zh = 9  # Chinese
    # int gt 10 as Unknown.


class CsfVal(TypedDict):
    value: Union[str, List[str]]
    extra: Optional[str]


class InvalidCsfException(Exception):
    """To record errors when reading .CSF files."""
    pass


class EditorIncompatibleWarning(UserWarning):
    """To hint that 'RASResEditor' may not be able to open."""
    pass


def _codingvalue(valdata: bytearray):
    # bytes would throw TypeError
    valdata = bytearray(valdata)
    i = 0
    while i < len(valdata):
        # only ubyte can do (
        valdata[i] = c_ubyte(~valdata[i]).value
        i += 1
    return valdata


class CsfDocument(MutableMapping):
    version = 3
    language = 0

    def __init__(self):
        # str as label tag, list as values (or evals)
        self.__data: Dict[str, List[CsfVal]] = {}
        # it seems there are Csf(E)Vals without label ...
        # just leave them out = =
        # self.__isolated: List[Union[CsfVal, CsfEVal]] = []

    def __getitem__(self, lbl: str) -> Union[CsfVal, List[CsfVal]]:
        return (self.__data[lbl] if len(self.__data[lbl]) > 1
                else self.__data[lbl][0])

    def __setitem__(self, lbl: str, val: Union[CsfVal, List[CsfVal]]):
        # for multiple value, game would only use the first one.
        try:
            self.__data[lbl][0] = CsfVal(val)
        except Exception:
            if isinstance(val, list):
                if len(val) > 1:
                    warnings.warn(
                        f'Over 2 values in "{lbl}". '
                        "There may be no editors able to open it.",
                        EditorIncompatibleWarning, stacklevel=2)
                self.__data[lbl] = val
            else:
                self.__data[lbl] = [val]

    def __delitem__(self, lbl: str) -> None:
        return self.__data.__delitem__(lbl)

    def __iter__(self) -> Iterator:
        return self.__data.__iter__()

    def __len__(self) -> int:
        return self.__data.__len__()

    def getValidValue(self, label) -> Optional[str]:
        """Get the value really read by `game*.exe`."""
        try:
            return self.__data[label][0].get('value', '')
        except IndexError:
            return None

    def setdefault(self, label, string, *, extra=None):
        """Append a label which doesn't exist in document,
        with single `CsfVal`."""
        if label in self.__data:
            return
        self[label] = CsfVal(value=string, extra=extra)

    def __readheader(self, fp: FileIO):
        if fp.read(4).decode('ascii') != CSF_TAG:
            raise InvalidCsfException('NOT csf file')
        header = CsfHead(*unpack('LLLLL', fp.read(4 * 5)))
        return header

    def __readlabel(self, fp: FileIO):
        """Label:

        -----------
        offset | element
        ----|------
        00H | char tag[4]
        04H | DWORD numstr
        08H | DWORD lenlbl
        0CH | char lblname[lenlbl]

        consider it as a struct with char* char** elements.
        """
        if fp.read(4).decode('ascii') != LBL_TAG:
            raise InvalidCsfException('NOT a proper Csf Label')

        numstr, lenlbl = unpack('LL', fp.read(4 * 2))
        lblname = fp.read(lenlbl).decode('ascii')
        self.__data[lblname] = []

        i = 0
        while i < numstr:
            self.__data[lblname].append(self.__readvalue(fp))
            i += 1

    __EV_SWITCH = {
        EVAL_TAG: True,
        VAL_TAG: False,
    }

    def __readvalue(self, fp: FileIO):
        """Value:

        ---------------------
        offset   |  element
        ---------|-----------
        00H      | char tag[4]
        04H      | DWORD lenval
        08H      | byte val[2 * lenval]
        (08+2*lenval)H     | leneval
        (08+2*lenval+04)H  | char eval[leneval]

        According to modenc,
        `val[2 * lenval]` was unicode encoded, with XORed bits content.
        """
        if (isev := self.__EV_SWITCH.get(fp.read(4).decode('ascii'))) is None:
            raise InvalidCsfException('Not a proper Csf Label Value')

        length = unpack('L', fp.read(4))[0] << 1
        data = CsfVal(value=_codingvalue(fp.read(length)).decode('utf-16'),
                      extra=None)
        if isev:
            elength = unpack('L', fp.read(4))[0]
            data['extra'] = fp.read(elength).decode('ascii')
        return data

    def readCsf(self, filepath):
        with open(filepath, 'rb') as fp:
            h = self.__readheader(fp)
            i = 0
            while i < h.numlabels:
                self.__readlabel(fp)
                i += 1
        return len(self)

    @property
    def header(self) -> CsfHead:
        numstr = 0
        for i in self.__data.values():
            numstr += len(i)
        return CsfHead(self.version, len(self), numstr, 0, self.language)

    def __writelabels(self, fp: FileIO, lbl: str, val: List[CsfVal]):
        fp.write(pack(f'<4sLL{len(lbl)}s',
                      LBL_TAG.encode('ascii'), len(val), len(lbl),
                      lbl.encode('ascii')))
        for i in val:  # value
            lv = len(i['value'])
            isev = bool(i.get('extra'))  # not None, not empty
            fp.write(pack(
                f'<4sL{lv << 1}s',
                (EVAL_TAG if isev else VAL_TAG).encode('ascii'), lv,
                _codingvalue(i['value'].encode('utf-16'))[2:]))
            if isev:
                ev = len(i['extra'])
                fp.write(pack(f'<L{ev}s', ev, i['extra'].encode('ascii')))

    def writeCsf(self, filepath):
        # force little endian.
        with open(filepath, 'wb') as fp:
            fp.write(pack('<4sLLLLL',  # header
                          CSF_TAG.encode('ascii'), *self.header))
            for k, v in self.__data.items():
                self.__writelabels(fp, k, v)


def csfToJSONV2(self: CsfDocument, jsonfilepath, encoding='utf-8', indent=2):
    """Convert to Shimakaze Csf-JSON v2 Document."""
    def toJSONValue(val: Union[CsfVal, List[CsfVal]]) -> dict:
        if isinstance(val, list):
            ret = {'values': [toJSONValue(i) for i in val]}
        else:
            ret = val.copy()
            if '\n' in ret['value']:
                ret['value'] = ret['value'].split('\n')
            if not ret['extra']:
                del ret['extra']
        return ret

    ret = JSON_HEAD.copy()
    ret['version'] = self.version
    ret['language'] = self.language
    ret['data'] = {}
    for k, v in self.items():
        v = toJSONValue(v)
        if 'values' not in v and 'extra' not in v:
            v = v['value']
        ret['data'][k] = v
    with open(jsonfilepath, 'w', encoding=encoding) as fp:
        json.dump(ret, fp, ensure_ascii=False, indent=indent)


def importJSONV2(jsonfilepath, encoding='utf-8') -> CsfDocument:
    def fromJSON(val: Union[Dict[str, Any], List[str], Optional[str]]):
        if val is None:  # latest standard - empty val
            ret = CsfVal(value="", extra=None)
        elif isinstance(val, str):  # one-line val
            ret = CsfVal(value=val, extra=None)
        elif isinstance(val, list):  # multi-line val
            ret = CsfVal(value='\n'.join(val), extra=None)
        elif isinstance(val, dict) and 'values' not in val:  # Eval
            ret = CsfVal(value=val['value'], extra=val.get('extra'))
            if val['value'] is None:
                ret['value'] = ""
            elif isinstance(val['value'], list):
                ret['value'] = '\n'.join(val['value'])
        else:
            ret = []
            for i in val['values']:  # multiple values, needs further process.
                ret.append(fromJSON(i))
        return ret

    ret = CsfDocument()
    with open(jsonfilepath, 'r', encoding=encoding) as fp:
        src = json.load(fp)
    ret.version = src['version']
    ret.language = src['language']
    for k, v in src['data'].items():
        ret[k] = fromJSON(v)
    return ret


def csfToXMLV1(self: CsfDocument, xmlfilepath, indent='\t'):
    """Convert to Shimakaze Csf-XML V1 Document.
    Only `utf-8` supported."""
    def parseCsfVal(elem_node: et.Element, v: CsfVal):
        if v['extra']:  # not None, not empty
            elem_node.attrib['extra'] = v['extra']
        elem_node.text = v['value']

    root = et.Element('Resources', {'protocol': '1',
                                    'version': str(self.version),
                                    'language': str(self.language)})
    for k, v in self.items():
        lbl = et.SubElement(root, 'Label', {'name': k})
        if isinstance(v, dict):
            parseCsfVal(lbl, v)
        else:
            vals = et.SubElement(lbl, 'Values')
            for i in v:
                ei = et.SubElement(vals, 'Value')
                parseCsfVal(ei, i)
    formatted = minidom.parseString(et.tostring(root, 'utf-8'))
    xmllines = formatted.toprettyxml(
        indent, encoding='utf-8').decode().split('\n')
    with open(xmlfilepath, 'w', encoding='utf-8') as fp:
        fp.write(f'{xmllines[0]}\n')
        fp.write(XML_MODEL)
        cnt = 1
        while cnt < len(xmllines):
            fp.write(f'{xmllines[cnt]}\n')
            cnt += 1


def importXMLV1(xmlfilepath) -> CsfDocument:
    # keep compat with external styled xml
    indent_filter = regex(r'\n[ \t]+', FULL_MATCH)
    ret = CsfDocument()
    root = et.parse(xmlfilepath).getroot()  # Resources
    ret.version = int(root.attrib.get('version', '3'))
    ret.language = int(root.attrib.get('language', '0'))
    for lbl in root:
        if (_ := list(lbl)) and _[0].tag == 'Values':  # multi values
            lblvalue = (CsfVal(value="", extra=None)
                        if _[0].text is None
                        else [CsfVal(value=indent_filter.sub('\n', v.text),
                                     extra=v.attrib.get('extra'))
                              for v in list(_[0])])
        else:
            lbleval = lbl.attrib.get('extra')
            lblvalue = (CsfVal(value=indent_filter.sub('\n', lbl.text),
                               extra=lbleval)
                        if lbl.text is not None
                        else CsfVal(value="", extra=lbleval))
        ret[lbl.attrib['name']] = lblvalue
    return ret


def csfToSimpleYAML(self: CsfDocument, yamlfilepath,
                    encoding='utf-8', indent=2):
    """Convert to SIMPLE yaml file."""
    yaml_special_signs = YAML_SPECIAL_SIGNS_1.copy()
    yaml_special_signs.append(YAML_SPECIAL_SIGNS_2)
    # manual dump as the pyyaml output is too ugly
    with open(yamlfilepath, 'w', encoding=encoding) as fp:
        fp.write(f'{YAML_SCHEMA_HEADER}\n'
                 f'lang: {self.language}\n'
                 f'version: {self.version}\n'
                 '---\n')  # header
        fp.write(f'{YAML_SCHEMA_BODY}\n')  # body
        for k in self.keys():
            v = self.getValidValue(k)
            if v is None:
                v = "''"
            elif '\n' in v:  # multi line (with (>-) or without (>) special)
                prefix = '>\n'
                for i in yaml_special_signs:
                    if i in v:
                        prefix = '>-\n'
                        break
                v = (prefix + v).replace('\n', f'\n{indent * " "}')
            elif YAML_SPECIAL_SIGNS_2 in v:
                v = f'"{v}"'
            else:
                for i in YAML_SPECIAL_SIGNS_1:
                    if i in v:
                        v = f"'{v}'"
                        break
            if ': ' in k:
                k = f"'{k}'"
            fp.write(f'{k}: {v}\n')


def importSimpleYAML(yamlfilepath, encoding='utf-8') -> CsfDocument:
    with open(yamlfilepath, 'r', encoding=encoding) as fp:
        header, data = yaml.load_all(fp.read(), yaml.FullLoader)
    ret = CsfDocument()
    ret.language = header['lang']
    ret.version = header['version']
    for k, v in data.items():
        # may there be some pure digits considered as int
        ret[k] = CsfVal(value=str(v), extra=None)
    return ret

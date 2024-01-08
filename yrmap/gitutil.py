# -*- encoding: utf-8 -*-
# @File   : __init__.py
# @Time   : 2023/11/14 17:40:39
# @Author : Chloride

from os.path import exists, join

from ..ini import INIClass


def _ex_regs(map_: INIClass, registry, target: INIClass):
    reg = map_.getTypeList(registry)
    if not reg:
        return
    del map_[registry]
    target[registry] = dict(zip(range(len(reg)), reg))
    _ex_entries(map_, target, *reg)


def _ex_entries(map_: INIClass, target: INIClass, *entries):
    for i in entries:
        if i not in map_:
            continue
        target[i] = map_[i]
        del map_[i]


def splitMap(self: INIClass, out_dir: str):
    """To split map files to smaller files (git friendly).

    e.g. `exportMapElems(yr_a07, 'D:/yra07')` =>
    - `D:/yra07/(...).ini`
    - `D:/yra07/*mappkg.bin`
    - `D:/yra07/partial.ini`
    """
    t = INIClass()
    _ex_regs(self, 'Houses', t)
    _ex_regs(self, 'Countries', t)
    with open(join(out_dir, 'houses.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_regs(self, 'TaskForces', t)
    with open(join(out_dir, 'taskforces.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_regs(self, 'ScriptTypes', t)
    with open(join(out_dir, 'scripttypes.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_regs(self, 'TeamTypes', t)
    with open(join(out_dir, 'teamtypes.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_entries(self, t, 'AITriggerTypes', 'AITriggerTypesEnable')
    with open(join(out_dir, 'AI_local.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_entries(self, t,
                'VariableNames', 'Triggers', 'Events', 'Actions')
    with open(join(out_dir, 'logics.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_entries(self, t, 'Infantry', 'Units', 'Aircraft', 'Structures')
    with open(join(out_dir, 'technos.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_entries(self, t, 'Smudge', 'Terrain',)
    with open(join(out_dir, 'natures.ini'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_entries(self, t, 'IsoMapPack5')
    with open(join(out_dir, 'isomappkg.bin'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    _ex_entries(self, t, 'OverlayPack', 'OverlayDataPack')
    with open(join(out_dir, 'ovlmappkg.bin'), 'w', encoding='utf-8') as fp:
        t.writeStream(fp)
    t.clear()

    with open(join(out_dir, 'partial.ini'), 'w', encoding='utf-8') as fp:
        self.writeStream(fp)


def joinMap(src_dir, out_name):
    """To merge partial files into a map file.

    PS: src_dir shouldn't end with `\\` or `/`!

    e.g. `compilePartialMap('D:/yra07', 'antrc')` => `D:/yra07/antrc.map`
    """
    if not exists(src_dir):
        return
    if not exists(join(src_dir, "partial.ini")):
        return
    out = INIClass()
    out.read(join(src_dir, "partial.ini"),
             join(src_dir, 'houses.ini'),
             join(src_dir, 'taskforces.ini'),
             join(src_dir, 'scripttypes.ini'),
             join(src_dir, 'teamtypes.ini'),
             join(src_dir, 'AI_local.ini'),
             join(src_dir, 'logics.ini'),
             join(src_dir, 'technos.ini'),
             join(src_dir, 'natures.ini'),
             join(src_dir, 'isomappkg.bin'),
             join(src_dir, 'ovlmappkg.bin'),
             encoding='utf-8')
    with open(join(src_dir, f"{out_name}.map"), 'w',
              encoding='utf-8') as fp:
        out.writeStream(fp)

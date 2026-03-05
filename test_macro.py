# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# test_macro.py
import macro_collector

result = macro_collector.get_macro_indicators()
if result:
    print(f"현재 매크로 상태: {result}")

# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pynini
from pynini.lib import pynutil

from nemo_text_processing.inverse_text_normalization.he.graph_utils import (
    NEMO_DIGIT,
    GraphFst,
    delete_and,
    delete_extra_space,
    delete_space,
    delete_zero_or_one_space,
    insert_space,
)
from nemo_text_processing.inverse_text_normalization.he.taggers.cardinal import CardinalFst
from nemo_text_processing.inverse_text_normalization.he.utils import get_abs_path, integer_to_text


class TimeFst(GraphFst):
    """
    Finite state transducer for classifying time in Hebrew.
    Conversion is made only when am / pm time is not ambiguous!
        e.g. שלוש דקות לחצות -> time { minutes: "57" hours: "23" }
        e.g. באחת ושתי דקות בצהריים -> time { prefix: "ב" hours: "1" minutes: "02" suffix: "צהריים" }
        e.g. שתיים ועשרה בבוקר -> time { hours: "2" minutes: "10" suffix: "בוקר" }
        e.g. שתיים ועשרה בצהריים -> time { hours: "2" minutes: "10" suffix: "צהריים" }
        e.g. שתיים עשרה ושלוש דקות אחרי הצהריים -> time { hours: "12" minutes: "03" suffix: "צהריים" }
        e.g. רבע לשש בערב -> time { minutes: "45" hours: "5" suffix: "ערב" }

    """

    def __init__(self):
        super().__init__(name="time", kind="classify")

        # hours, minutes, seconds, suffix, zone, style, speak_period
        to_hour_graph = pynini.string_file(get_abs_path("data/time/to_hour.tsv"))
        minute_to_graph = pynini.string_file(get_abs_path("data/time/minute_to.tsv"))
        suffix_graph = pynini.string_file(get_abs_path("data/time/time_suffix.tsv"))

        time_prefix = pynini.string_file(get_abs_path("data/prefix.tsv"))
        time_prefix_graph = pynutil.insert("prefix: \"") + time_prefix + pynutil.insert("\"") + insert_space

        optional_time_prefix_graph = pynini.closure(time_prefix_graph, 0, 1)

        graph_minute_verbose = pynini.string_map(
            [
                ("שלושת רבעי", "45"),
                ("חצי", "30"),
                ("רבע", "15"),
                ("עשרים", "20"),
                ("עשרה", "10"),
                ("חמישה", "05"),
                ("דקה", "01"),
                ("שתי", "02"),
            ]
        )

        graph_minute_to_verbose = pynini.string_map(
            [("רבע", "45"), ("עשרה", "50"), ("חמישה", "55"), ("עשרים", "40"), ("עשרים וחמישה", "35"), ("דקה", "59"),]
        )

        # only used for < 1000 thousand -> 0 weight
        cardinal = pynutil.add_weight(CardinalFst().graph_no_exception, weight=-0.7)

        labels_hour = [integer_to_text(x, only_fem=True)[0] for x in range(1, 13)]
        labels_minute_single = [integer_to_text(x, only_fem=True)[0] for x in range(2, 10)]
        labels_minute_double = [integer_to_text(x, only_fem=True)[0] for x in range(10, 60)]

        midnight = pynini.string_map([("חצות", "0")])
        graph_hour = pynini.union(*labels_hour) @ cardinal
        graph_hour |= midnight
        add_leading_zero_to_double_digit = pynutil.insert("0") + NEMO_DIGIT
        graph_minute_single = pynini.union(*labels_minute_single) @ cardinal @ add_leading_zero_to_double_digit
        graph_minute_double = pynini.union(*labels_minute_double) @ cardinal

        final_graph_hour = pynutil.insert("hours: \"") + graph_hour + pynutil.insert("\"")

        graph_minute = pynini.union(pynutil.insert("00"), graph_minute_single, graph_minute_double)

        final_suffix = pynutil.insert("suffix: \"") + suffix_graph + pynutil.insert("\"")
        final_suffix = delete_space + insert_space + final_suffix

        graph_h_and_m = (
            final_graph_hour
            + delete_space
            + delete_and
            + insert_space
            + pynutil.insert("minutes: \"")
            + pynini.union(graph_minute_single, graph_minute_double, graph_minute_verbose)
            + pynutil.insert("\"")
            + (pynini.closure(delete_space + pynutil.delete("דקות"), 0, 1))
        )

        graph_special_m_to_h_suffix_time = (
            pynutil.insert("minutes: \"")
            + graph_minute_to_verbose
            + pynutil.insert("\"")
            + delete_space
            + pynutil.delete("ל")
            + insert_space
            + pynutil.insert("hours: \"")
            + to_hour_graph
            + pynutil.insert("\"")
        )

        graph_m_to_h_suffix_time = (
            pynutil.insert("minutes: \"")
            + pynini.union(graph_minute_single, graph_minute_double) @ minute_to_graph
            + pynutil.insert("\"")
            + pynini.closure(delete_space + pynutil.delete("דקות"), 0, 1)
            + delete_space
            + pynutil.delete("ל")
            + insert_space
            + pynutil.insert("hours: \"")
            + to_hour_graph
            + pynutil.insert("\"")
        )

        graph_h = (
            optional_time_prefix_graph
            + delete_zero_or_one_space
            + final_graph_hour
            + delete_extra_space
            + pynutil.insert("minutes: \"")
            + (pynutil.insert("00") | graph_minute)
            + pynutil.insert("\"")
            + final_suffix
        )

        midnight_graph = (
            optional_time_prefix_graph
            + delete_zero_or_one_space
            + pynutil.insert("hours: \"")
            + midnight
            + pynutil.insert("\"")
            + insert_space
            + pynutil.insert("minutes: \"")
            + (pynutil.insert("00") | graph_minute)
            + pynutil.insert("\"")
        )

        graph_midnight_and_m = (
            pynutil.insert("hours: \"")
            + midnight
            + pynutil.insert("\"")
            + delete_space
            + delete_and
            + insert_space
            + pynutil.insert("minutes: \"")
            + pynini.union(graph_minute_single, graph_minute_double, graph_minute_verbose)
            + pynutil.insert("\"")
            + (pynini.closure(delete_space + pynutil.delete("דקות"), 0, 1))
        )

        to_midnight_verbose_graph = (
            pynutil.insert("minutes: \"")
            + graph_minute_to_verbose
            + pynutil.insert("\"")
            + delete_space
            + pynutil.delete("ל")
            + insert_space
            + pynutil.insert("hours: \"")
            + to_hour_graph
            + pynutil.insert("\"")
        )

        graph_m_to_midnight = (
            pynutil.insert("minutes: \"")
            + pynini.union(graph_minute_single, graph_minute_double) @ minute_to_graph
            + pynutil.insert("\"")
            + pynini.closure(delete_space + pynutil.delete("דקות"), 0, 1)
            + delete_space
            + pynutil.delete("ל")
            + insert_space
            + pynutil.insert("hours: \"")
            + to_hour_graph
            + pynutil.insert("\"")
        )

        final_graph_midnight = (
            optional_time_prefix_graph
            + delete_zero_or_one_space
            + (midnight_graph | to_midnight_verbose_graph | graph_m_to_midnight | graph_midnight_and_m)
        )

        final_graph = (
            optional_time_prefix_graph
            + delete_zero_or_one_space
            + (graph_h_and_m | graph_special_m_to_h_suffix_time | graph_m_to_h_suffix_time)
            + final_suffix
        )
        final_graph |= graph_h
        final_graph |= final_graph_midnight

        final_graph = self.add_tokens(final_graph.optimize())
        self.fst = final_graph.optimize()

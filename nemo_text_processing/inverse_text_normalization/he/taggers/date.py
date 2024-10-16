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
    GraphFst,
    delete_extra_space,
    delete_space,
    insert_space,
)
from nemo_text_processing.inverse_text_normalization.he.utils import get_abs_path


def _get_month_name_graph():
    """
    Transducer for month, e.g. march -> march
    """
    month_graph = pynini.string_file(get_abs_path("data/months.tsv"))
    return month_graph


def _get_year_graph(graph_two_digits, graph_thousands):
    """
    Transducer for year, e.g. twenty twenty -> 2020
    """
    year_graph = pynini.union(
        (graph_two_digits + delete_space + graph_two_digits), graph_thousands  # 20 19, 40 12, 20 20
    )  # 2012 - assuming no limit on the year

    year_graph.optimize()
    return year_graph


class DateFst(GraphFst):
    """
    Finite state transducer for classifying date in Hebrew,
        e.g. אחד במאי אלף תשע מאות שמונים ושלוש -> date { day: "1" month_prefix: "ב" month: "5" year: "1983" }
        e.g. הראשון ביוני אלפיים ושתיים עשרה -> date { day_prefix: "ה" day: "1" month_prefix: "ב" month: "6" year: "2012" }
        e.g. העשירי ביוני -> date { day_prefix: "ה" day: "10" month_prefix: "ב" month: "6" }
        e.g. מרץ אלף תשע מאות שמונים ותשע -> date { month: "מרץ" year: "1989" }
        e.g. בינואר עשרים עשרים -> date { month_prefix: "ב" month: "ינואר" year: "2020" }

    Args:
        cardinal: CardinalFst
        ordinal: OrdinalFst
    """

    def __init__(self, cardinal: GraphFst, ordinal: GraphFst):
        super().__init__(name="date", kind="classify")

        prefix_graph = pynini.string_file(get_abs_path("data/prefix.tsv"))

        ordinal_graph = ordinal.graph
        two_digits_graph = cardinal.graph_two_digit

        day_graph = pynutil.add_weight(two_digits_graph | ordinal_graph, -0.7)
        day_graph = pynutil.insert("day: \"") + day_graph + pynutil.insert("\"")
        optional_day_prefix_graph = pynini.closure(
            pynutil.insert("day_prefix: \"") + prefix_graph + pynutil.insert("\"") + insert_space, 0, 1
        )

        month_names = _get_month_name_graph()
        month_names_graph = pynutil.insert("month: \"") + month_names + pynutil.insert("\"")

        month_name2number = pynini.string_file(get_abs_path("data/months_name2number.tsv"))
        month_name2number_graph = pynutil.insert("month: \"") + pynini.invert(month_name2number) + pynutil.insert("\"")

        month_number2number = pynini.string_file(get_abs_path("data/months_number2number.tsv"))
        month_number2number_graph = (
            pynutil.insert("month: \"") + pynini.invert(month_number2number) + pynutil.insert("\"")
        )

        all_month_graph = month_name2number_graph | month_number2number_graph

        month_prefix_graph = pynutil.insert("month_prefix: \"") + prefix_graph + pynutil.insert("\"") + insert_space
        optional_month_prefix_graph = pynini.closure(month_prefix_graph, 0, 1)

        year_graph = _get_year_graph(two_digits_graph, cardinal.graph_thousands)

        graph_year = delete_extra_space + pynutil.insert("year: \"") + year_graph + pynutil.insert("\"")

        graph_dm = (
            optional_day_prefix_graph
            + day_graph
            + insert_space
            + delete_space
            + optional_month_prefix_graph
            + month_name2number_graph
        )

        graph_dmy = (
            optional_day_prefix_graph
            + day_graph
            + insert_space
            + delete_space
            + month_prefix_graph
            + all_month_graph
            + graph_year
        )

        graph_my = optional_month_prefix_graph + month_names_graph + graph_year

        optional_prefix_graph = pynini.closure(prefix_graph, 0, 1)
        year_only_prefix = optional_prefix_graph + pynini.union("שנה", "שנת")

        graph_y_only = pynutil.insert("year_only_prefix: \"") + year_only_prefix + pynutil.insert("\"") + graph_year

        final_graph = graph_dm | graph_dmy | graph_my | graph_y_only
        final_graph = self.add_tokens(final_graph)
        self.fst = final_graph.optimize()

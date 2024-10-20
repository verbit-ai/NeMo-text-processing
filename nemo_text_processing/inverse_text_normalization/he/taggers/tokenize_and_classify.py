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

import logging
import os

import pynini
from pynini.lib import pynutil

from nemo_text_processing.inverse_text_normalization.he.graph_utils import GraphFst
from nemo_text_processing.inverse_text_normalization.he.taggers.cardinal import CardinalFst
from nemo_text_processing.inverse_text_normalization.he.taggers.date import DateFst
from nemo_text_processing.inverse_text_normalization.he.taggers.decimal import DecimalFst
from nemo_text_processing.inverse_text_normalization.he.taggers.measure import MeasureFst
from nemo_text_processing.inverse_text_normalization.he.taggers.ordinal import OrdinalFst
from nemo_text_processing.inverse_text_normalization.he.taggers.punctuation import PunctuationFst
from nemo_text_processing.inverse_text_normalization.he.taggers.time import TimeFst
from nemo_text_processing.inverse_text_normalization.he.taggers.whitelist import WhiteListFst
from nemo_text_processing.inverse_text_normalization.he.taggers.word import WordFst
from nemo_text_processing.text_normalization.en.graph_utils import delete_extra_space, delete_space, generator_main


class ClassifyFst(GraphFst):
    """
    Final class that composes all other classification grammars. This class can process an entire sentence.
    For deployment, this grammar will be compiled and exported to OpenFst Finite State Archive (FAR) File.
    More details to deployment at NeMo/tools/text_processing_deployment.

    Args:
        cache_dir: path to a dir with .far grammar file. Set to None to avoid using cache.
        overwrite_cache: set to True to overwrite .far files
        whitelist: path to a file with whitelist replacements
    """

    def __init__(self, cache_dir: str = None, overwrite_cache: bool = False, whitelist: str = None, input_case: str = None):

        super().__init__(name="tokenize_and_classify", kind="classify")

        far_file = None
        if cache_dir is not None and cache_dir != "None":
            os.makedirs(cache_dir, exist_ok=True)
            far_file = os.path.join(cache_dir, f"he_itn.far")
        if not overwrite_cache and far_file and os.path.exists(far_file):
            self.fst = pynini.Far(far_file, mode="r")["tokenize_and_classify"]
            logging.info(f"ClassifyFst.fst was restored from {far_file}.")
        else:
            logging.info(f"Creating ClassifyFst grammars.")

            cardinal = CardinalFst()
            cardinal_graph = cardinal.fst

            ordinal = OrdinalFst(cardinal)

            decimal = DecimalFst(cardinal)
            decimal_graph = decimal.fst

            measure_graph = MeasureFst(cardinal=cardinal, decimal=decimal).fst
            date_graph = DateFst(ordinal=ordinal, cardinal=cardinal).fst
            word_graph = WordFst().fst
            time_graph = TimeFst().fst
            whitelist_graph = WhiteListFst(input_file=whitelist).fst
            punct_graph = PunctuationFst().fst

            classify = (
                pynutil.add_weight(whitelist_graph, 1.01)
                | pynutil.add_weight(time_graph, 1.1)
                | pynutil.add_weight(date_graph, 1.09)
                | pynutil.add_weight(decimal_graph, 1.1)
                | pynutil.add_weight(measure_graph, 1.1)
                | pynutil.add_weight(cardinal_graph, 1.1)
                | pynutil.add_weight(word_graph, 100)
                # NOTE: we convert ordinals in Hebrew only if it is a part of a date!
                # this is why it is commented out.
                # | pynutil.add_weight(ordinal_graph, 1.09)
            )

            punct = pynutil.insert("tokens { ") + pynutil.add_weight(punct_graph, weight=1.1) + pynutil.insert(" }")
            token = pynutil.insert("tokens { ") + classify + pynutil.insert(" }")
            token_plus_punct = (
                pynini.closure(punct + pynutil.insert(" ")) + token + pynini.closure(pynutil.insert(" ") + punct)
            )

            graph = token_plus_punct + pynini.closure(delete_extra_space + token_plus_punct)
            graph = delete_space + graph + delete_space

            self.fst = graph.optimize()

            if far_file:
                generator_main(far_file, {"tokenize_and_classify": self.fst})
                logging.info(f"ClassifyFst grammars are saved to {far_file}.")

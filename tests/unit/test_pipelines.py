# -*- coding: utf-8 -*-
#
# This file is part of hepcrawl.
# Copyright (C) 2016, 2017 CERN.
#
# hepcrawl is a free software; you can redistribute it and/or modify it
# under the terms of the Revised BSD License; see LICENSE file for
# more details.

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import mock
import os

import pytest

from scrapy.spider import Spider
from inspire_schemas.api import validate

from hepcrawl.spiders import arxiv_spider
from hepcrawl.pipelines import InspireAPIPushPipeline

from hepcrawl.testlib.fixtures import fake_response_from_file


@pytest.fixture
def spider():
    mock_spider = mock.create_autospec(Spider)
    mock_spider.name = 'arXiv'
    mock_spider.state = {}
    return mock_spider


@pytest.fixture
def json_spider_record(tmpdir):
    from scrapy.http import TextResponse
    spider = arxiv_spider.ArxivSpider()
    items = spider.parse(
        fake_response_from_file(
            'arxiv/sample_arxiv_record10.xml',
            response_type=TextResponse,
        ),
    )
    parsed_record = items.next()
    assert parsed_record
    return spider, parsed_record


@pytest.fixture
def expected_response():
    responses_dir = os.path.dirname(os.path.realpath(__file__))
    expected_path = os.path.join(
        responses_dir,
        'responses/arxiv/sample_arxiv_record10_parsed.json',
    )
    with open(expected_path, 'rb') as expected_fd:
        result = expected_fd.read()

    return json.loads(result)


def test_prepare_payload(
    tmpdir, json_spider_record, spider, expected_response,
):
    """Test that the generated payload is ok."""
    _, json_record = json_spider_record
    os.environ['SCRAPY_JOB'] = 'scrapy_job'
    os.environ['SCRAPY_FEED_URI'] = 'scrapy_feed_uri'
    os.environ['SCRAPY_LOG_FILE'] = 'scrapy_log_file'

    pipeline = InspireAPIPushPipeline()

    pipeline.open_spider(spider)
    pipeline.process_item(json_record, spider)

    result = pipeline._prepare_payload(spider)

    # acquisition_source has a timestamp
    result['results_data'][0]['acquisition_source'].pop('datetime')
    expected_response['results_data'][0]['acquisition_source'].pop('date')

    for record in result['results_data']:
        validate(record, 'hep')

    for res, exp in zip(
        result['results_data'],
        expected_response['results_data'],
    ):
        for key in res:
            assert key in exp
            assert res[key] == exp[key]

    assert result == expected_response

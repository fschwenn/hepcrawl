# -*- coding: utf-8 -*-
#
# This file is part of hepcrawl.
# Copyright (C) 2016 CERN.
#
# hepcrawl is a free software; you can redistribute it and/or modify it
# under the terms of the Revised BSD License; see LICENSE file for
# more details.

"""Spider for Springer."""

import re
import os

from tempfile import mkdtemp

from scrapy import Request, Selector
from scrapy.spiders import XMLFeedSpider
from ..utils import get_first
from ..dateutils import create_valid_date
from ..items import HEPRecord
from ..loaders import HEPLoader
from ..mappings import OA_LICENSES

from ..utils import (
    unzip_xml_files
)

class SpringerSpider(XMLFeedSpider):
    """Springer crawler.

    Extracts from metadata:
    title,
    """

    name = 'Springer'
    iterator = 'xml'
    itertag = 'Publisher'

    def __init__(self, zip_file=None, xml_file=None, **kwargs):
        """Construct Springer spider."""
        super(SpringerSpider, self).__init__(**kwargs)
        self.zip_file = zip_file
        self.xml_file = xml_file

    def start_requests(self):
        """Spider can be run on zip file, or individual record xml"""
        if self.zip_file:
            yield Request(self.zip_file, callback=self.handle_package)
        elif self.xml_file:
            yield Request(
                self.xml_file,
                meta={"xml_url": self.xml_file},
            )

    def handle_package(self, response):
        """Handle the zip package and yield a request for every XML found."""
        self.log("Visited %s" % response.url)
        filename = os.path.basename(response.url).rstrip(".zip")
        # TMP dir to extract zip packages:
        target_folder = mkdtemp(prefix="springer_" + filename + "_", dir="/tmp/")

        zip_filepath = response.url.replace("file://", "")
        xml_files = unzip_xml_files(zip_filepath, target_folder)
        # The xml files shouldn't be removed after processing; they will
        # be later uploaded to Inspire. So don't remove any tmp files here.
        for xml_file in xml_files:
            xml_url = u"file://{0}".format(os.path.abspath(xml_file))
            yield Request(
                xml_url,
                meta={"package_path": zip_filepath,
                      "xml_url": xml_url},
            )

    def _get_pubnotes(self, response, isbook):
        #journalname
        jtitle = response.xpath("//JournalInfo/JournalTitle/text()").extract_first()
        if jtitle:
            pubnote = {'journal_title' : jtitle}
        else:
            pubnote = {}
        #volume
        volumestart = response.xpath("//VolumeIDStart/text()").extract_first()
        volumeend = response.xpath("//VolumeIDEnd/text()").extract_first()
        if volumestart == volumeend:
            pubnote['journal_volume'] = volumestart
        elif volumestart and volumeend:
            pubnote['journal_volume'] = '%s-%s' % (volumestart, volumeend)
        elif volumestart:
            pubnote['journal_volume'] = volumestart
        #issue
        issuestart = response.xpath("//IssueIDStart/text()").extract_first()
        issueend = response.xpath("//IssueIDEnd/text()").extract_first()
        if issuestart == issueend:
            pubnote['journal_issue'] = issuestart
        elif issuestart and issueend:
            pubnote['journal_issue'] = '%s-%s' % (issuestart, issueend)
        elif issuestart:
            pubnote['journal_issue'] = issuestart
        #year
        pubnote['year'] = response.xpath("//PrintDate/Year/text()").extract_first()
        if not pubnote['year']:
            pubnote['year'] = response.xpath("//IssueHistory/CoverDate/Year/text()").extract_first()
        #pagerange
        firstpage = response.xpath("//ArticleInfo/ArticleFirstPage/text()|//ChapterInfo/ChapterFirstPage/text()").extract_first()
        lastpage = response.xpath("//ArticleInfo/ArticleLastPage/text()|//ChapterInfo/ChapterLastPage/text()").extract_first()
        articleid = response.xpath("//ArticleInfo/ArticleCitationID/text()").extract_first()
        if articleid:
            pubnote['artid'] = articleid
        else:
            if firstpage:
                pubnote['page_start'] = firstpage
            if lastpage:
                pubnote['page_end'] = lastpage
        #2nd pubnote
        pubnote2 = False
        for spara in response.xpath("//ArticleNote/SimplePara/text()").extract():
            if re.search('Original.*published in', spara) or re.search('Translated from', spara):
                pubnote2 = {}
                secondpubnote = re.sub('.*published in *', '', spara)
                secondpubnote = re.sub('.*Translated from *', '', secondpubnote)
                snotedataparts = re.split(' *, *', secondpubnote)
                pubnote2['journal_title'] = snotedataparts[0]
                for part in snotedataparts[1:]:
                    if re.search('Vol. ', part):
                        pubnote2['journal_volume'] = re.sub('Vol. ', '', part)
                    elif re.search('No. ', part):
                        pubnote2['journal_issue'] = re.sub('No. ', '', part)
                    elif re.search('pp\.? *', part):
                        pages = re.sub('pp\.? *', '', re.sub('\.', '', part))
                        pagesparts = re.split('\D+', pages)
                        pubnote2['page_start'] = pagesparts[0]
                        if len(pagesparts) > 1:
                            pubnote2['page_end'] = pagesparts[1]
                    elif re.search('\d\d\d\d', part):
                        pubnote2['year'] = re.sub('.*?(\d\d\d\d).*', r'\1', part)
        if pubnote2:
            return [pubnote, pubnote2]
        else:
            return [pubnote]

    def _get_keywords(self, response):
        kwdict = {}
        for kwg in response.xpath('//KeywordGroup'):
            heading = kwg.xpath('./Heading/text()').extract_first()
            kwdict[heading] = kwg.xpath('./Keyword/text()').extract()

        return kwdict

    def _get_publicationdate(self, response):
        pdate = response.xpath("//ArticleHistory/OnlineDate/Year/text()").extract_first()
        month = response.xpath("//ArticleHistory/OnlineDate/Month/text()").extract_first()
        if month:
            pdate = '%s-%02i' % (pdate, int(month))
        day = response.xpath("//ArticleHistory/OnlineDate/Day/text()").extract_first()
        if day:
            pdate = '%s-%02i' % (pdate, int(day))
        if not pdate:
            pdate = response.xpath("//CoverDate/Year/text()").extract_first()
            month = response.xpath("//CoverDate/Month/text()").extract_first()
            if month:
                pdate = '%s-%02i' % (pdate, int(month))
        return pdate

    def _get_authors(self, authorgroup, lookonlyforedtitors):
        authors = []
        if lookonlyforedtitors:
            xauthors = authorgroup.xpath("//Editor")
        else:
            xauthors = authorgroup.xpath("//Author")
        for xauthor in xauthors:
            author = {}
            if lookonlyforedtitors:
                author['role'] = 'Editor'
            author['givennames'] = [' '.join(xauthor.xpath("./*/GivenName/text()").extract())]
            author['surname'] = ' '.join(xauthor.xpath("./*/FamilyName/text()").extract())
            author['email'] = xauthor.xpath("./Contact/Email/text()").extract_first()
            author['affiliations'] = []
            orcid = xauthor.xpath("@ORCID").extract_first()
            if orcid:
                author['orcid'] = re.sub('.*\/', '', orcid)
            try:
                for affid in re.split(' ', xauthor.xpath("@AffiliationIDS").extract_first()):
                    affL1 = authorgroup.xpath('//Affiliation[@ID="%s"]/*/text()' % (affid)).extract()
                    aff = ', '.join(affL1)
                    affL2 = authorgroup.xpath('//Affiliation[@ID="%s"]/*/*/text()' % (affid)).extract()
                    if affL2:
                        if affL1:
                            aff = aff + '; ' + ', '.join(affL2)
                        else:
                            aff = ', '.join(affL2)
                    author['affiliations'].append({'value' : re.sub(', \n *', '', aff)})
            except:
                print 'no affiliations'
            authors.append(author)
        return authors

    def _get_references(self, response):
        #the possibility of structured references in Springer's xml is not always used
        references = []
        for ref in response.xpath("//Bibliography/Citation"):
            nr = ref.xpath("./CitationNumber/text()").extract_first()
            if nr:
                nr = re.sub('\D', '', nr)
            bib = ref.xpath("./BibUnstructured").xpath('string()').extract_first()
            bib = re.sub(' *\n *', '', bib)
            bib = re.sub(' \[INSPIRE\]', '', bib)
            doi = ref.xpath('./BibArticle/Occurrence[@Type="DOI"]/Handle/text()').extract_first()
            if doi:
                bib = '%s; DOI: %s' % (bib, doi)
            references.append({'raw_reference' : bib})
        return references

    def _get_doctype(self, response):
        doctype = 'Published'
        for category in response.xpath("//ArticleInfo/ArticleCategory/text()").extract():
            if category in ['Review', 'Review Article', 'Invited Review']:
                doctype = 'Review'
            elif category in ['Erratum', 'Addendum']:
                pass
            elif re.search('^Proceedings of', category):
                doctype = 'ConferencePaper'
        for book in response.xpath("//BookInfo/BookDOI"):
            doctype = 'Book'
        for chapter in response.xpath("//ChapterInfo/ChapterDOI"):
            doctype = 'BookChapter'
        return doctype

    def _get_isbns(self, response):
        isbns = []
        for pisbn in response.xpath("//BookInfo/BookPrintISBN/text()").extract():
            isbns.append({'medium' : 'Print', 'value' : re.sub('\-', '', pisbn)})
        for eisbn in response.xpath("//BookInfo/BookElectronicISBN/text()").extract():
            isbns.append({'medium' : 'ebook', 'value' : re.sub('\-', '', eisbn)})
        return isbns

    def parse_node(self, response, node):
        record = HEPLoader(item=HEPRecord(), response=response)
        #authors
        if response.xpath("//EditorGroup"):
            for xauthor in response.xpath("//EditorGroup/Editor"):
                record.add_value('authors', self._get_authors(xauthor, True))
        else:
            for xauthor in response.xpath("//AuthorGroup/Author"):
                record.add_value('authors', self._get_authors(xauthor, False))
        #doctype
        doctype = self._get_doctype(response)
        record.add_value('journal_doctype', doctype)
        if doctype == 'Book':
            isbook = True
            #DOI
            record.add_xpath('dois', '//BookInfo/BookDOI/text()')
            #ISBN
            isbns = self._get_isbns(response)
            #record.add_value('isbns', isbns)
            #title
            title = response.xpath('//BookInfo/BookTitle').extract()
            if title:
                record.add_value('title', title)
            #Copyright
            record.add_xpath('copyright_holder', '//BookCopyright/CopyrightHolderName/text()')
            record.add_xpath('copyright_year', '//BookCopyright/CopyrightYear/text()')
            record.add_xpath('copyright_statement', '//BookCopyright/CopyrightStandardText/text()')
        else:
            isbook = False
            #DOI
            record.add_xpath('dois', '//ArticleInfo/ArticleDOI/text()|//ChapterInfo/ChapterDOI/text()')
            #title
            title = response.xpath('//ArticleInfo/ArticleTitle|//ChapterInfo/ChapterTitle').extract()
            if title:
                record.add_value('title', title)
            #Copyright
            for copyright in response.xpath('//ArticleCopyright|//ChapterCopyright'):
                record.add_value('copyright_holder', copyright.xpath('./CopyrightHolderName/text()').extract())
                record.add_value('copyright_year', copyright.xpath('./CopyrightYear/text()').extract())
                record.add_value('copyright_year', copyright.xpath('./CopyrightStandardText/text()').extract())
        #abstract
        abstract = response.xpath('//Abstract/Para').extract()
        if abstract:
            record.add_value('abstract', abstract)
        #licence
        record.add_xpath('license_url', '//License//RefSource/text()')
        #PBN
        pubnotes = self._get_pubnotes(response, isbook)
        record.add_value('publication_info', pubnotes)
        #arXiv number
        record.add_xpath('arxiv_eprints', '//ArticleInfo/ArticleExternalID[@Type="arXiv"]/text()')
        #keywords and PACS
        keywords = self._get_keywords(response)
        for heading in keywords.keys():
            if heading == 'Keywords':
                for kw in keywords[heading]:
                    record.add_value('free_keywords', kw)
            elif heading in ['PACS Nos', 'PACS No.', 'PACS NOs', 'PACS No']:
                for kw in keywords[heading]:
                    record.add_value('classification_numbers', kw)
        #publicationdate
        pdate = self._get_publicationdate(response)
        record.add_value('date_published', pdate)
        #ISBN
        #if isbook:
        #    isbns = self._get_isbns(response)
        #    if isbns:
        #        record.add_value('isbns', isbns)
        #references
        record.add_value('references', self._get_references(response))
        xml_file = response.meta.get("xml_url")
        return record.load_item()

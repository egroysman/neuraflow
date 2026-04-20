from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class BaseDataSource(ABC):
    @abstractmethod
    def get_customer_summaries(self, uploaded_file_bytes: Optional[bytes] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_customer_detail(self, customer_id: str, uploaded_file_bytes: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
        pass